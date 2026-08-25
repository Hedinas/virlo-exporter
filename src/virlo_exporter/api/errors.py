from __future__ import annotations

from typing import Any


class VirloError(Exception):
    """Base error safe to present in the UI."""

    def __init__(self, message: str, *, status_code: int | None = None, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = details


class AuthenticationError(VirloError):
    pass


class NetworkError(VirloError):
    pass


class InsufficientBalanceError(VirloError):
    def __init__(self, details: dict[str, Any] | None = None):
        details = details or {}
        required = float(details.get("required_credits", 0)) / 100
        remaining = float(details.get("remaining_credits", 0)) / 100
        super().__init__(
            f"Insufficient Virlo balance. Required ${required:.2f}; available ${remaining:.2f}.",
            status_code=402,
            details=details,
        )


class RateLimitError(VirloError):
    def __init__(self, retry_after: float, details: Any = None):
        super().__init__(
            f"Rate limited. Retry after {retry_after:g}s.", status_code=429, details=details
        )
        self.retry_after = retry_after


class MalformedResponseError(VirloError):
    pass


class PaginationError(VirloError):
    pass
