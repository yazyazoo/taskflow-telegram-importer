from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProgressSnapshot:
    downloaded_bytes: int
    total_bytes: int
    bytes_per_second: float
    eta_seconds: int | None


class ProgressMeter:
    def __init__(self, *, started_at: float) -> None:
        self._started_at = started_at

    def snapshot(self, *, current: int, total: int, now: float) -> ProgressSnapshot:
        elapsed = max(now - self._started_at, 0.0)
        speed = current / elapsed if elapsed else 0.0
        remaining = max(total - current, 0)
        eta = round(remaining / speed) if total > 0 and speed > 0 else None
        return ProgressSnapshot(current, total, speed, eta)
