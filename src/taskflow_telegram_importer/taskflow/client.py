from __future__ import annotations

import asyncio
from pathlib import Path
import time
from typing import Any, Mapping

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.http import JsonTransport


class TaskFlowClient:
    def __init__(
        self,
        transport: JsonTransport,
        *,
        base_url: str,
        token: str,
        filesystem_integration_code: str,
        timeout_seconds: float,
        reconciliation_poll_seconds: float,
        reconciliation_timeout_seconds: float,
    ) -> None:
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._integration_code = filesystem_integration_code
        self._timeout_seconds = timeout_seconds
        self._poll_seconds = reconciliation_poll_seconds
        self._reconciliation_timeout = reconciliation_timeout_seconds

    async def list_presets(self) -> tuple[dict[str, Any], ...]:
        data = await self._get("/workflow-presets")
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise ImporterError("TaskFlow returned an invalid preset catalog")
        return tuple(data)

    async def resolve_filesystem_packages(
        self, files: tuple[tuple[Path, int], ...]
    ) -> tuple[str, ...]:
        integrations = await self._get("/integrations")
        if not isinstance(integrations, list):
            raise ImporterError("TaskFlow returned invalid integrations")
        integration = next(
            (
                item
                for item in integrations
                if isinstance(item, dict)
                and item.get("code") == self._integration_code
                and item.get("type") == "filesystem"
            ),
            None,
        )
        if integration is None or not isinstance(integration.get("id"), str):
            raise ImporterError("TaskFlow filesystem integration is unavailable")
        integration_id = integration["id"]
        await self._post(f"/integrations/{integration_id}/refresh", None)
        expected = {str(path): size for path, size in files}
        deadline = time.monotonic() + self._reconciliation_timeout
        while True:
            packages = await self._get("/packages")
            matches = _match_packages(packages, integration_id, expected)
            if len(matches) == len(expected):
                return tuple(matches[path] for path in expected)
            if time.monotonic() >= deadline:
                missing = sorted(set(expected) - matches)
                raise ImporterError(
                    "TaskFlow did not reconcile published files: " + ", ".join(missing)
                )
            await asyncio.sleep(self._poll_seconds)

    async def create_and_start(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        created = await self._post("/workflows", payload)
        if not isinstance(created, dict) or not isinstance(created.get("id"), str):
            raise ImporterError("TaskFlow did not return a workflow ID")
        workflow_id = created["id"]
        started = await self._post(f"/workflows/{workflow_id}/start", None)
        if not isinstance(started, dict):
            raise ImporterError("TaskFlow returned invalid workflow start data")
        return started

    async def _get(self, path: str) -> Any:
        response = await self._transport.request(
            "GET",
            self._base_url + path,
            headers=self._headers,
            timeout_seconds=self._timeout_seconds,
        )
        if response.status != 200:
            raise ImporterError(f"TaskFlow GET failed with HTTP {response.status}")
        return response.data

    async def _post(self, path: str, body: Mapping[str, Any] | None) -> Any:
        response = await self._transport.request(
            "POST",
            self._base_url + path,
            headers=self._headers,
            body=body,
            timeout_seconds=self._timeout_seconds,
        )
        if response.status not in {200, 201, 202}:
            raise ImporterError(f"TaskFlow POST failed with HTTP {response.status}")
        return response.data


def _match_packages(data: Any, integration_id: str, expected: dict[str, int]) -> dict[str, str]:
    if not isinstance(data, list):
        raise ImporterError("TaskFlow returned invalid packages")
    matches: dict[str, str] = {}
    for package in data:
        if (
            not isinstance(package, dict)
            or package.get("integration_id") != integration_id
            or package.get("status") != "ready"
            or package.get("workflow_id") is not None
            or not isinstance(package.get("id"), str)
            or not isinstance(package.get("details"), dict)
        ):
            continue
        path = package["details"].get("file")
        size = package["details"].get("size")
        if isinstance(path, str) and path in expected and size == expected[path]:
            matches[path] = package["id"]
    return matches
