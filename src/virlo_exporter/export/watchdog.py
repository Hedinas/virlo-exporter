from __future__ import annotations

WAITING_THRESHOLD_SECONDS = 120
LONG_STALL_THRESHOLD_SECONDS = 300


class StallWatchdog:
    """Tracks silence since the last *meaningful* progress event for one
    export -- a new page, new records, an API response, a stage transition
    -- rather than total stage duration. A stage that's been running for
    four minutes because it has 59 real pages to fetch is not stalled; a
    stage that hasn't heard anything back for two minutes might be."""

    def __init__(
        self,
        *,
        waiting_threshold: float = WAITING_THRESHOLD_SECONDS,
        long_stall_threshold: float = LONG_STALL_THRESHOLD_SECONDS,
    ) -> None:
        self.waiting_threshold = waiting_threshold
        self.long_stall_threshold = long_stall_threshold
        self.last_progress_at: float | None = None

    def record_progress(self, now: float) -> None:
        self.last_progress_at = now

    def silence_seconds(self, now: float) -> float:
        if self.last_progress_at is None:
            return 0.0
        return max(0.0, now - self.last_progress_at)

    def status_message(self, now: float) -> str | None:
        """None while progress is recent enough to say nothing; otherwise a
        user-facing status line. Never signals failure -- the caller keeps
        waiting/retrying per the normal HTTP retry/backoff policy."""
        silence = self.silence_seconds(now)
        if self.last_progress_at is None or silence < self.waiting_threshold:
            return None
        minutes, seconds = divmod(int(silence), 60)
        elapsed = f"{minutes}m {seconds:02d}s"
        if silence >= self.long_stall_threshold:
            return f"Virlo response is taking unusually long — no new data for {elapsed}"
        return f"Waiting for Virlo… no new data for {elapsed}"
