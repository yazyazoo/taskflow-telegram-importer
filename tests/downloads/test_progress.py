from taskflow_telegram_importer.downloads.progress import ProgressMeter


def test_progress_meter_reports_speed_and_eta_from_downloaded_bytes() -> None:
    meter = ProgressMeter(started_at=100.0)

    snapshot = meter.snapshot(current=50_000_000, total=100_000_000, now=110.0)

    assert snapshot.downloaded_bytes == 50_000_000
    assert snapshot.total_bytes == 100_000_000
    assert snapshot.bytes_per_second == 5_000_000
    assert snapshot.eta_seconds == 10


def test_progress_meter_handles_unknown_total_without_fake_eta() -> None:
    meter = ProgressMeter(started_at=100.0)

    snapshot = meter.snapshot(current=1_000, total=0, now=102.0)

    assert snapshot.bytes_per_second == 500
    assert snapshot.eta_seconds is None
