from __future__ import annotations

import pytest

from taskflow_telegram_importer.http import JsonResponse
from taskflow_telegram_importer.tmdb import TmdbClient


class TransportStub:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def request(self, method, url, *, headers=None, query=None, body=None, timeout_seconds=30):
        self.calls.append((method, url, headers, query, body, timeout_seconds))
        return JsonResponse(200, self.payload)


@pytest.mark.asyncio
async def test_search_movie_uses_configured_api_key_and_normalizes_candidates() -> None:
    transport = TransportStub({"results": [{
        "id": 38074,
        "title": "Zeder",
        "original_title": "Zeder",
        "release_date": "1983-08-25",
        "overview": "Horror italiano",
        "poster_path": "/zeder.jpg",
    }]})
    client = TmdbClient(
        transport,
        base_url="https://api.themoviedb.org/3",
        api_key="secret-key",
        language="it-IT",
        timeout_seconds=12,
        max_results=5,
    )

    candidates = await client.search("movie", "Zeder", 1983)

    assert [(item.tmdb_id, item.title, item.year) for item in candidates] == [
        (38074, "Zeder", 1983)
    ]
    assert transport.calls[0][1].endswith("/search/movie")
    assert transport.calls[0][3] == {
        "api_key": "secret-key",
        "language": "it-IT",
        "query": "Zeder",
        "year": "1983",
    }


@pytest.mark.asyncio
async def test_search_tv_uses_first_air_date_and_limits_results() -> None:
    transport = TransportStub({"results": [
        {"id": index, "name": f"Show {index}", "original_name": f"Original {index}",
         "first_air_date": "2026-01-01", "overview": "", "poster_path": None}
        for index in range(1, 8)
    ]})
    client = TmdbClient(
        transport,
        base_url="https://api.themoviedb.org/3",
        api_key="key",
        language="it-IT",
        timeout_seconds=30,
        max_results=3,
    )

    candidates = await client.search("tv", "Show", 2026)

    assert len(candidates) == 3
    assert transport.calls[0][3]["first_air_date_year"] == "2026"
