from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from virlo_exporter.storage.database import Database


class StageTracker:
    """Emit and persist honest export stage transitions."""

    def __init__(
        self,
        database: Database,
        export_id: int,
        progress: Callable[[dict[str, Any]], None] | None,
    ) -> None:
        self.database = database
        self.export_id = export_id
        self.progress = progress
        self.sequence = 0
        self.current: dict[str, Any] | None = None

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    def start(self, stage: str, label: str, *, detail: str | None = None) -> None:
        self.sequence += 1
        self.current = {
            "event": "stage",
            "export_id": self.export_id,
            "sequence": self.sequence,
            "stage": stage,
            "label": label,
            "status": "running",
            "started_at": self._now(),
            "completed_at": None,
            "summary": None,
            "detail": detail,
        }
        self._publish(persist=True)

    def finish(
        self, status: str = "complete", *, summary: str | None = None, detail: str | None = None
    ) -> None:
        if self.current is None:
            return
        self.current["status"] = status
        self.current["completed_at"] = self._now()
        self.current["summary"] = summary
        if detail is not None:
            self.current["detail"] = detail
        self._publish(persist=True)

    def update(
        self,
        *,
        current: int | None = None,
        total: int | None = None,
        message: str | None = None,
        page: int | None = None,
    ) -> None:
        if self.current is None:
            return
        if current is not None:
            self.current["current"] = current
        if total is not None:
            self.current["total"] = total
        if message is not None:
            self.current["message"] = message
        if page is not None:
            self.current["page"] = page
        self._publish(persist=False)

    def _publish(self, *, persist: bool) -> None:
        assert self.current is not None
        event = dict(self.current)
        if persist:
            self.database.upsert_export_stage(self.export_id, event)
        if self.progress:
            self.progress(event)

