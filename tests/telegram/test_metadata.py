from types import SimpleNamespace

from taskflow_telegram_importer.sessions import VideoMetadata
from taskflow_telegram_importer.telegram.metadata import extract_video_metadata


def test_extracts_telegram_video_metadata_without_downloading_media() -> None:
    media_file = SimpleNamespace(width=1920, height=816, duration=3319.92)

    assert extract_video_metadata(media_file) == VideoMetadata(
        width=1920,
        height=816,
        duration_seconds=3319.92,
    )


def test_missing_or_invalid_telegram_metadata_remains_unavailable() -> None:
    media_file = SimpleNamespace(width=0, height=None, duration=-1)

    assert extract_video_metadata(media_file) == VideoMetadata()
