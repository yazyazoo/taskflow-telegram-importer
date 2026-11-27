from __future__ import annotations

from pathlib import Path

import pytest

from taskflow_telegram_importer.automation import QuickWorkflowOrchestrator
from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.sessions import (
    EditorialHint,
    FileState,
    ImportFile,
    ImportMode,
    ImportSession,
    QuickStage,
    QuickWorkflowDraft,
    SessionState,
    TmdbCandidate,
)


class TaskFlowStub:
    def __init__(self):
        self.payload = None

    async def resolve_filesystem_packages(self, files):
        assert files == ((Path("/gate/Show_2026/episode.mkv"), 123),)
        return ("1234567",)

    async def create_and_start(self, payload):
        self.payload = payload
        return {"id": "7654321", "status": "queued"}


@pytest.mark.asyncio
async def test_quick_orchestrator_uses_persisted_selection_and_package_ids() -> None:
    taskflow = TaskFlowStub()
    orchestrator = QuickWorkflowOrchestrator(taskflow)
    candidate = TmdbCandidate(42, "Show", "Show", 2026, "", None, ("Dramma",))
    draft = QuickWorkflowDraft(
        stage=QuickStage.PUBLISHED,
        media_kind="tv",
        query_title="Show",
        query_year=2026,
        candidates=(candidate,),
        selected_tmdb_id=42,
        preset_code="direct-media",
        cleanup_on_success=True,
        sub_ita=False,
    )
    session = ImportSession(
        "session", 20, 10, SessionState.PUBLISHED,
        files=(ImportFile(1, "episode.mkv", 123, FileState.PUBLISHED),),
        editorial_hint=EditorialHint("Show", 2026),
        mode=ImportMode.QUICK,
        quick=draft,
        published_paths=(Path("/gate/Show_2026/episode.mkv"),),
    )

    updated = await orchestrator.execute(session)

    assert updated.quick is not None
    assert updated.quick.stage is QuickStage.STARTED
    assert updated.quick.taskflow_package_ids == ("1234567",)
    assert updated.quick.workflow_id == "7654321"
    assert taskflow.payload == {
        "packages": ["1234567"],
        "preset": "direct-media",
        "workflow_name": "Show_2026",
        "cleanup_on_success": True,
        "media_kind": "tv",
        "tmdb": {"tmdb_id": 42},
    }


@pytest.mark.asyncio
async def test_quick_orchestrator_rejects_selection_without_genres() -> None:
    taskflow = TaskFlowStub()
    orchestrator = QuickWorkflowOrchestrator(taskflow)
    candidate = TmdbCandidate(42, "Show", "Show", 2026, "", None)
    session = ImportSession(
        "session",
        20,
        10,
        SessionState.PUBLISHED,
        files=(ImportFile(1, "episode.mkv", 123, FileState.PUBLISHED),),
        editorial_hint=EditorialHint("Show", 2026),
        mode=ImportMode.QUICK,
        quick=QuickWorkflowDraft(
            stage=QuickStage.PUBLISHED,
            media_kind="tv",
            candidates=(candidate,),
            selected_tmdb_id=42,
            preset_code="direct-media",
        ),
        published_paths=(Path("/gate/Show_2026/episode.mkv"),),
    )

    with pytest.raises(ImporterError, match="genres"):
        await orchestrator.execute(session)

    assert taskflow.payload is None
