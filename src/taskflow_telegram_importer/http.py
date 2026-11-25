from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import ImporterError


@dataclass(frozen=True, slots=True)
class JsonResponse:
    status: int
    data: Any


class JsonTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        timeout_seconds: float = 30,
    ) -> JsonResponse: ...


class UrllibJsonTransport:
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        timeout_seconds: float = 30,
    ) -> JsonResponse:
        return await asyncio.to_thread(
            self._request,
            method,
            url,
            headers or {},
            query or {},
            body,
            timeout_seconds,
        )

    @staticmethod
    def _request(method, url, headers, query, body, timeout_seconds) -> JsonResponse:
        if query:
            url = f"{url}?{urlencode(query)}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request_headers = {"Accept": "application/json", **headers}
        if payload is not None:
            request_headers["Content-Type"] = "application/json"
        request = Request(url, data=payload, headers=request_headers, method=method)
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
                data = json.loads(raw.decode("utf-8")) if raw else None
                return JsonResponse(int(response.status), data)
        except HTTPError as exc:
            raw = exc.read()
            detail = raw.decode("utf-8", errors="replace") if raw else str(exc)
            raise ImporterError(f"HTTP {exc.code}: {detail}") from exc
        except (URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
            raise ImporterError(f"HTTP request failed: {type(exc).__name__}: {exc}") from exc
