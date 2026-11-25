from __future__ import annotations

from typing import Any, Literal

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.http import JsonTransport
from taskflow_telegram_importer.sessions import TmdbCandidate


class TmdbClient:
    def __init__(
        self,
        transport: JsonTransport,
        *,
        base_url: str,
        api_key: str,
        language: str,
        timeout_seconds: float,
        max_results: int,
    ) -> None:
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._language = language
        self._timeout_seconds = timeout_seconds
        self._max_results = max_results

    async def search(
        self, media_kind: Literal["movie", "tv"], title: str, year: int
    ) -> tuple[TmdbCandidate, ...]:
        if media_kind not in {"movie", "tv"}:
            raise ImporterError("media kind must be movie or tv")
        title = title.strip()
        if not title or not 1000 <= year <= 9999:
            raise ImporterError("TMDB search requires title and four-digit year")
        year_key = "year" if media_kind == "movie" else "first_air_date_year"
        response = await self._transport.request(
            "GET",
            f"{self._base_url}/search/{media_kind}",
            query={
                "api_key": self._api_key,
                "language": self._language,
                "query": title,
                year_key: str(year),
            },
            timeout_seconds=self._timeout_seconds,
        )
        if response.status != 200 or not isinstance(response.data, dict):
            raise ImporterError("TMDB search failed")
        values = response.data.get("results")
        if not isinstance(values, list):
            raise ImporterError("TMDB search returned invalid data")
        candidates = tuple(
            candidate
            for value in values[: self._max_results]
            if (candidate := _candidate(value, media_kind)) is not None
        )
        if not candidates:
            raise ImporterError("TMDB search returned no candidates")
        return candidates


def _candidate(value: Any, media_kind: str) -> TmdbCandidate | None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), int):
        return None
    title_key = "title" if media_kind == "movie" else "name"
    original_key = "original_title" if media_kind == "movie" else "original_name"
    date_key = "release_date" if media_kind == "movie" else "first_air_date"
    title = value.get(title_key)
    date = value.get(date_key)
    if not isinstance(title, str) or not title.strip() or not isinstance(date, str):
        return None
    try:
        year = int(date[:4])
    except ValueError:
        return None
    original = value.get(original_key)
    overview = value.get("overview")
    poster = value.get("poster_path")
    return TmdbCandidate(
        tmdb_id=value["id"],
        title=title.strip(),
        original_title=original.strip() if isinstance(original, str) else title.strip(),
        year=year,
        overview=overview.strip() if isinstance(overview, str) else "",
        poster_path=poster if isinstance(poster, str) else None,
    )
