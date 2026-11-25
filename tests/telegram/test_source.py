from pathlib import Path

import pytest

from taskflow_telegram_importer.telegram.source import TelethonFileSource


class FakeClient:
    def __init__(self) -> None:
        self.message = object()
        self.calls = []

    async def get_messages(self, chat_id, *, ids):
        self.calls.append(("get", chat_id, ids))
        return self.message

    async def download_media(self, message, *, file, progress_callback):
        self.calls.append(("download", message, file))
        Path(file).write_bytes(b"complete-video")
        await progress_callback(8, 14)
        await progress_callback(14, 14)
        return str(file)


@pytest.mark.asyncio
async def test_telethon_source_downloads_message_directly_to_requested_path(
    tmp_path: Path,
) -> None:
    client = FakeClient()
    source = TelethonFileSource(client)
    progress = []

    async def report(current: int, total: int) -> None:
        progress.append((current, total))

    target = tmp_path / "episode.mkv.part"
    downloaded = await source.download(20, 100, target, report)

    assert downloaded == target
    assert target.read_bytes() == b"complete-video"
    assert client.calls == [
        ("get", 20, 100),
        ("download", client.message, str(target)),
    ]
    assert progress == [(8, 14), (14, 14)]


@pytest.mark.asyncio
async def test_telethon_source_rejects_missing_message(tmp_path: Path) -> None:
    client = FakeClient()
    client.message = None
    source = TelethonFileSource(client)

    with pytest.raises(Exception, match="message is no longer available"):
        await source.download(20, 100, tmp_path / "episode.part", lambda *_: None)
