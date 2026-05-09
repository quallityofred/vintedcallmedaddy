import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import patch

from app.models import Monitor
from app.scheduler.tasks import (
    EMPTY_THRESHOLD_FAST,
    EMPTY_THRESHOLD_SLOW,
    INTERVAL_STEP_DOWN_FAST,
    INTERVAL_STEP_UP,
    MAX_INTERVAL_SECONDS,
    _get_effective_interval,
    _is_peak_time,
    _normalize_adaptive_interval,
    _reset_interval_if_scaled_from_time_window,
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: str


def make_monitor(original_interval: int, interval_sec: int, consecutive_empty: int = 0) -> Monitor:
    return Monitor(
        name="check",
        original_url="https://example.com",
        params_json=json.dumps({"_original_interval": original_interval}),
        domains_json="[]",
        interval_sec=interval_sec,
        is_active=True,
        consecutive_empty=consecutive_empty,
    )


@contextmanager
def mocked_hour(hour: int):
    fake_now = datetime(2026, 5, 8, hour, 0, tzinfo=timezone.utc)
    with patch("app.scheduler.tasks.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = fake_now
        mocked_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        yield


def check_restore_after_night() -> CheckResult:
    monitor = make_monitor(original_interval=120, interval_sec=600)
    restored = _reset_interval_if_scaled_from_time_window(monitor)
    return CheckResult(
        name="night_restore",
        passed=restored == 120,
        details=f"restored={restored}, expected=120",
    )


def check_restore_after_offpeak() -> CheckResult:
    monitor = make_monitor(original_interval=120, interval_sec=300)
    restored = _reset_interval_if_scaled_from_time_window(monitor)
    return CheckResult(
        name="offpeak_restore",
        passed=restored == 120,
        details=f"restored={restored}, expected=120",
    )


def check_speedup_after_found_items() -> CheckResult:
    monitor = make_monitor(original_interval=120, interval_sec=180)
    monitor.interval_sec = _reset_interval_if_scaled_from_time_window(monitor)
    new_interval = max(int(monitor.interval_sec * INTERVAL_STEP_DOWN_FAST), 120)
    return CheckResult(
        name="speedup_after_find",
        passed=new_interval == 125,
        details=f"new_interval={new_interval}, expected=125",
    )


def check_slowdown_cap() -> CheckResult:
    monitor = make_monitor(
        original_interval=120,
        interval_sec=MAX_INTERVAL_SECONDS - 5,
        consecutive_empty=EMPTY_THRESHOLD_SLOW - 1,
    )
    monitor.interval_sec = _reset_interval_if_scaled_from_time_window(monitor)
    monitor.consecutive_empty += 1
    new_interval = int(monitor.interval_sec * INTERVAL_STEP_UP)
    capped = min(new_interval, MAX_INTERVAL_SECONDS)
    return CheckResult(
        name="slowdown_cap",
        passed=capped == MAX_INTERVAL_SECONDS,
        details=f"capped={capped}, max={MAX_INTERVAL_SECONDS}",
    )


def check_night_to_peak_not_sticky() -> CheckResult:
    monitor = make_monitor(original_interval=120, interval_sec=600)
    restored = _reset_interval_if_scaled_from_time_window(monitor)
    with mocked_hour(12):
        effective = _get_effective_interval(restored)
        is_peak = _is_peak_time()
    return CheckResult(
        name="night_to_peak_transition",
        passed=is_peak and effective == 120,
        details=f"is_peak={is_peak}, restored={restored}, effective={effective}",
    )


def check_peak_threshold_constant() -> CheckResult:
    with mocked_hour(12):
        threshold = EMPTY_THRESHOLD_FAST if _is_peak_time() else EMPTY_THRESHOLD_SLOW
    return CheckResult(
        name="peak_empty_threshold",
        passed=threshold == EMPTY_THRESHOLD_FAST,
        details=f"threshold={threshold}, expected={EMPTY_THRESHOLD_FAST}",
    )


def check_normalization_floor() -> CheckResult:
    monitor = make_monitor(original_interval=120, interval_sec=60)
    normalized = _normalize_adaptive_interval(monitor)
    return CheckResult(
        name="normalization_floor",
        passed=normalized == 120,
        details=f"normalized={normalized}, expected=120",
    )


def main() -> int:
    checks = [
        check_restore_after_night(),
        check_restore_after_offpeak(),
        check_speedup_after_found_items(),
        check_slowdown_cap(),
        check_night_to_peak_not_sticky(),
        check_peak_threshold_constant(),
        check_normalization_floor(),
    ]

    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"[{status}] {check.name}: {check.details}")

    failed = [check.name for check in checks if not check.passed]
    if failed:
        print(f"FAILED_CHECKS={','.join(failed)}")
        return 1

    print("ALL_CHECKS_PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())