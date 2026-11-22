from taskflow_telegram_importer.sessions import EditorialHint, parse_editorial_hint


def test_parses_caption_title_year_languages_and_quality() -> None:
    hint = parse_editorial_hint(
        ["Schumacher '94 - La Nascita Di Una Leggenda (2026 ITA/GER) [1080p]"],
        [],
    )

    assert hint == EditorialHint(
        title="Schumacher '94 - La Nascita Di Una Leggenda", year=2026
    )


def test_uses_first_non_blank_caption_line() -> None:
    hint = parse_editorial_hint(
        ["\n\nCape Fear (2025) [2160p]\nAltri dati", "Ignored (2020)"], []
    )

    assert hint == EditorialHint(title="Cape Fear", year=2025)


def test_falls_back_to_filename_when_caption_is_blank() -> None:
    hint = parse_editorial_hint(["  "], ["Dark Matter (2024) [1080p].mkv"])

    assert hint == EditorialHint(title="Dark Matter", year=2024)


def test_keeps_earlier_parentheses_in_title() -> None:
    hint = parse_editorial_hint(
        ["Title (Director's Cut) (2021 ITA) [1080p]"], []
    )

    assert hint == EditorialHint(title="Title (Director's Cut)", year=2021)


def test_invalid_year_returns_none() -> None:
    assert parse_editorial_hint(["Film (9999) [1080p]"], []) is None


def test_conflicting_filenames_return_none_instead_of_guessing() -> None:
    assert (
        parse_editorial_hint(
            [], ["First Film (2020).mkv", "Second Film (2021).mkv"]
        )
        is None
    )


def test_matching_episode_filenames_produce_one_hint() -> None:
    hint = parse_editorial_hint(
        [],
        [
            "Cape Fear (2025) S01E01 [1080p].mkv",
            "Cape Fear (2025) S01E02 [1080p].mkv",
        ],
    )

    assert hint == EditorialHint(title="Cape Fear", year=2025)
