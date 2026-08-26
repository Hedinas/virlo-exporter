from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .errors import MalformedResponseError, PaginationError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PageResult:
    records: list[dict[str, Any]]
    pages: int
    expected_total: int | None = None
    warnings: list[str] = field(default_factory=list)


class Paginator:
    def __init__(self, limit: int = 100, max_pages: int = 10000) -> None:
        self.limit = limit
        self.max_pages = max_pages

    def collect(
        self,
        fetch: Callable[[dict[str, int]], dict[str, Any]],
        resource: str,
        *,
        on_page: Callable[[int, int, int | None], None] | None = None,
        identity: Callable[[dict[str, Any]], str | None] | None = None,
    ) -> PageResult:
        """`identity` is a fallback dedup key for resources whose records
        carry neither "id" nor "run_id" (e.g. hashtags, hooks) -- without
        it, duplicate records for those resources are invisible to this
        method's own duplicate-id detection and are silently kept."""
        all_records: list[dict[str, Any]] = []
        seen_pages: set[str] = set()
        seen_ids: set[str] = set()
        warnings: list[str] = []
        expected_total: int | None = None
        page = 1
        offset = 0
        requests_made = 0
        previous_page_signature: str | None = None

        while True:
            if requests_made >= self.max_pages:
                raise PaginationError(f"Maximum page safety limit reached for {resource}.")
            requests_made += 1
            payload = fetch({"limit": self.limit, "page": page, "offset": offset})
            records, shape, metadata = self._unpack(payload, resource)
            page_ids = [
                str(record.get("id") or record.get("run_id"))
                for record in records
                if record.get("id") is not None or record.get("run_id") is not None
            ]
            signature_source = (
                json.dumps(sorted(page_ids), ensure_ascii=True)
                if page_ids
                else json.dumps(records, sort_keys=True, default=str, ensure_ascii=True)
            )
            page_signature = hashlib.sha256(signature_source.encode("utf-8")).hexdigest()
            logger.debug(
                "pagination resource=%s requested_page=%d requested_limit=%d "
                "response_page=%s response_count=%s actual_items=%d ids_preview=%s ids_hash=%s",
                resource,
                page,
                self.limit,
                metadata.get("page", metadata.get("offset")),
                metadata.get("count"),
                len(records),
                page_ids[:5],
                page_signature[:12],
            )
            if records and (
                page_signature == previous_page_signature or page_signature in seen_pages
            ):
                raise PaginationError(f"Repeated page detected while listing {resource}")
            previous_page_signature = page_signature
            if records:
                seen_pages.add(page_signature)

            for record in records:
                identifier = record.get("id") or record.get("run_id")
                if identifier is None and identity is not None:
                    identifier = identity(record)
                if identifier is not None:
                    key = str(identifier)
                    if key in seen_ids:
                        warnings.append(f"Duplicate {resource} id skipped: {key}")
                        continue
                    seen_ids.add(key)
                all_records.append(record)

            if on_page:
                total_hint = metadata.get("total") if isinstance(metadata, dict) else None
                on_page(requests_made, len(all_records), total_hint)

            if shape == "D":
                break
            if shape == "A":
                expected_total = int(metadata.get("total", len(all_records)))
                offset += len(records)
                page += 1
                if not records or offset >= expected_total or metadata.get("has_more") is False:
                    break
            elif shape == "B":
                expected_total = metadata.get("total")
                if not metadata.get("has_next_page", False):
                    break
                page += 1
            else:  # Shape C
                # Shape C's count is the size of this page, never a grand total.
                if len(records) < self.limit:
                    break
                page += 1
                offset += len(records)

        if expected_total is not None and len(all_records) != int(expected_total):
            warnings.append(
                f"Expected {expected_total} {resource} records; received {len(all_records)}."
            )
        return PageResult(all_records, requests_made, expected_total, warnings)

    @staticmethod
    def _unpack(
        payload: dict[str, Any], resource: str
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        if not isinstance(payload, dict) or "data" not in payload:
            raise MalformedResponseError(f"Malformed paginated response for {resource}.")
        data = payload["data"]
        pagination = payload.get("pagination")
        if isinstance(pagination, dict):
            if isinstance(data, dict):
                records = data.get(resource)
                if records is None and resource == "outliers":
                    records = data.get("creator_outliers")
                if not isinstance(records, list):
                    raise MalformedResponseError(f"Expected list data for {resource}.")
                return records, "B", pagination
            if not isinstance(data, list):
                raise MalformedResponseError(f"Expected list data for {resource}.")
            return data, "B", pagination
        if isinstance(data, list):
            return data, "D", {}
        if not isinstance(data, dict):
            raise MalformedResponseError(f"Expected object data for {resource}.")
        records = data.get(resource)
        if records is None and resource == "outliers":
            records = data.get("creator_outliers")
        if not isinstance(records, list):
            # A single bounded object remains useful as one RAW record.
            return [data], "D", {}
        if "total" in data or "has_more" in data:
            return records, "A", data
        if "count" in data:
            return records, "C", data
        return records, "D", data
