from __future__ import annotations

from virlo_exporter.export.watchdog import StallWatchdog


def test_regular_progress_prevents_stalled_state() -> None:
    watchdog = StallWatchdog()
    watchdog.record_progress(now=0)
    watchdog.record_progress(now=30)
    watchdog.record_progress(now=60)
    assert watchdog.status_message(now=90) is None


def test_no_progress_yet_produces_no_message() -> None:
    watchdog = StallWatchdog()
    assert watchdog.status_message(now=1000) is None


def test_silence_past_waiting_threshold_produces_waiting_message() -> None:
    watchdog = StallWatchdog(waiting_threshold=120, long_stall_threshold=300)
    watchdog.record_progress(now=0)
    message = watchdog.status_message(now=150)
    assert message is not None
    assert "Waiting for Virlo" in message
    assert "2m 30s" in message


def test_long_silence_past_long_stall_threshold_produces_unusually_long_message() -> None:
    watchdog = StallWatchdog(waiting_threshold=120, long_stall_threshold=300)
    watchdog.record_progress(now=0)
    message = watchdog.status_message(now=360)
    assert message is not None
    assert "unusually long" in message


def test_a_long_total_duration_alone_is_not_a_stall_if_progress_keeps_arriving() -> None:
    # Simulates a real ~4 minute videos stage (59 pages) where progress
    # arrives every few seconds the whole time -- total duration is long,
    # but silence between events never crosses the threshold.
    watchdog = StallWatchdog(waiting_threshold=120, long_stall_threshold=300)
    now = 0.0
    for _ in range(59):
        watchdog.record_progress(now=now)
        now += 4.0  # a new page roughly every 4 seconds
    assert watchdog.status_message(now=now) is None


def test_new_progress_after_a_stall_clears_the_message() -> None:
    watchdog = StallWatchdog(waiting_threshold=120, long_stall_threshold=300)
    watchdog.record_progress(now=0)
    assert watchdog.status_message(now=200) is not None
    watchdog.record_progress(now=210)  # a retry finally came back
    assert watchdog.status_message(now=215) is None
