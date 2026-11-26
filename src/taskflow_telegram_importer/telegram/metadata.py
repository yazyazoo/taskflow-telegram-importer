from __future__ import annotations

from taskflow_telegram_importer.sessions import VideoMetadata


def extract_video_metadata(media_file) -> VideoMetadata:
    return VideoMetadata(
        width=_positive_int(getattr(media_file, "width", None)),
        height=_positive_int(getattr(media_file, "height", None)),
        duration_seconds=_positive_float(getattr(media_file, "duration", None)),
    )


def _positive_int(value) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _positive_float(value) -> float | None:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None
