from pathlib import Path

import pytest

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.processors import VideoProcessor


def test_accepts_configured_extensions_case_insensitively_and_preserves_paths(
    tmp_path: Path,
) -> None:
    first = tmp_path / "One.MKV"
    second = tmp_path / "Two.mp4"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    processor = VideoProcessor((".mkv", ".mp4"), tmp_path)

    assert processor.process((first, second)) == (first, second)


@pytest.mark.parametrize("name", ["missing.mkv", "archive.7z.001", "notes.txt"])
def test_rejects_missing_or_unsupported_files(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    if name != "missing.mkv":
        path.write_bytes(b"data")
    processor = VideoProcessor((".mkv",), tmp_path)

    with pytest.raises(ImporterError):
        processor.process((path,))


def test_rejects_symlink_and_paths_outside_staging(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"video")
    link = staging / "link.mkv"
    link.symlink_to(outside)
    processor = VideoProcessor((".mkv",), staging)

    with pytest.raises(ImporterError):
        processor.process((outside,))
    with pytest.raises(ImporterError):
        processor.process((link,))
