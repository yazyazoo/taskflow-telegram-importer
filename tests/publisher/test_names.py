import pytest

from taskflow_telegram_importer.errors import ImporterError
from taskflow_telegram_importer.publisher import normalize_session_directory


def test_normalizes_unicode_title_and_repeated_separators() -> None:
    assert normalize_session_directory("  L'été---à   Roma__ ", 2024) == "L_été_à_Roma_2024"


@pytest.mark.parametrize("title", ["", "  ", "...", "___", "\x00bad"])
def test_rejects_empty_or_unsafe_normalized_titles(title: str) -> None:
    with pytest.raises(ImporterError):
        normalize_session_directory(title, 2024)


@pytest.mark.parametrize("year", [0, 999, 10000])
def test_rejects_invalid_year(year: int) -> None:
    with pytest.raises(ImporterError, match="year"):
        normalize_session_directory("Title", year)
