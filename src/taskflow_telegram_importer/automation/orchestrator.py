from __future__ import annotations

from dataclasses import replace
import re
import unicodedata

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.sessions import (
    FileState,
    ImportMode,
    ImportSession,
    QuickStage,
)


class QuickWorkflowOrchestrator:
    def __init__(self, taskflow_client) -> None:
        self._taskflow = taskflow_client

    async def execute(self, session: ImportSession) -> ImportSession:
        draft = session.quick
        if session.mode is not ImportMode.QUICK or draft is None:
            return session
        if draft.stage is QuickStage.STARTED:
            return session
        if session.editorial_hint is None or draft.selected_tmdb_id is None or not draft.preset_code:
            raise ImporterError("quick workflow draft is incomplete")
        selected = next(
            (item for item in draft.candidates if item.tmdb_id == draft.selected_tmdb_id),
            None,
        )
        if selected is None:
            raise ImporterError("selected TMDB candidate is unavailable")
        published_files = tuple(
            item for item in session.files if item.state is FileState.PUBLISHED
        )
        files = tuple(
            (path, item.expected_size)
            for path, item in zip(
                session.published_paths, published_files, strict=True
            )
        )
        package_ids = await self._taskflow.resolve_filesystem_packages(files)
        draft = replace(
            draft,
            stage=QuickStage.CREATING,
            taskflow_package_ids=package_ids,
            error=None,
        )
        payload = {
            "packages": list(package_ids),
            "preset": draft.preset_code,
            "workflow_name": _workflow_name(selected.title, selected.year),
            "cleanup_on_success": draft.cleanup_on_success,
            "media_kind": draft.media_kind,
            "tmdb": {"tmdb_id": selected.tmdb_id},
        }
        if draft.sub_ita:
            payload["renamer"] = {"sub_ita": True}
        workflow = await self._taskflow.create_and_start(payload)
        workflow_id = workflow.get("id")
        if not isinstance(workflow_id, str):
            raise ImporterError("TaskFlow did not return a workflow ID")
        return replace(
            session,
            quick=replace(
                draft,
                stage=QuickStage.STARTED,
                workflow_id=workflow_id,
            ),
        )


def _workflow_name(title: str, year: int) -> str:
    ascii_title = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    normalized = re.sub(r"\s+", "_", ascii_title)
    normalized = "".join(
        character
        for character in normalized
        if character.isalnum() or character in {"_", "-"}
    )
    normalized = re.sub(r"[_-]+", lambda match: "-" if "-" in match.group() else "_", normalized)
    normalized = normalized.strip("_-")
    if not normalized:
        raise ImporterError("TMDB title cannot produce a TaskFlow workflow name")
    return f"{normalized}_{year}"
