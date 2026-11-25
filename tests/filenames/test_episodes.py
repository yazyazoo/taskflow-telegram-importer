from taskflow_telegram_importer.filenames import EpisodePattern, normalize_episode_token


PATTERNS = (
    EpisodePattern(
        r"(?i)(?<![A-Za-z0-9])S(?P<season>\d{1,2})E(?P<first>\d{1,3})(?:(?P<repeated>(?:E\d{1,3})+)|-(?:(?:S(?P<last_season>\d{1,2}))?E)(?P<last>\d{1,3}))?(?![A-Za-z0-9]|-(?:E\d|S\d{1,2}E))",
        r"(?i)E(?P<episode>\d{1,3})",
    ),
    EpisodePattern(
        r"(?i)(?<![A-Za-z0-9])(?P<season>\d{1,2})x(?P<first>\d{1,3})(?P<repeated>(?:x\d{1,3})+)?(?![A-Za-z0-9])",
        r"(?i)x(?P<episode>\d{1,3})",
    ),
)


def test_normalizes_nxnn_token_without_touching_the_rest_of_the_filename() -> None:
    assert normalize_episode_token("Show.1x10.1080p.mkv", PATTERNS) == (
        "Show.S01E10.1080p.mkv"
    )


def test_normalizes_repeated_episode_token() -> None:
    assert normalize_episode_token("Show.2x01x02.mkv", PATTERNS) == (
        "Show.S02E01E02.mkv"
    )


def test_normalizes_sxxexx_range_from_shared_taskflow_grammar() -> None:
    assert normalize_episode_token("Show.S01E01-E03.mkv", PATTERNS) == (
        "Show.S01E01E02E03.mkv"
    )


def test_leaves_filename_without_one_unambiguous_token_unchanged() -> None:
    assert normalize_episode_token("Movie.2026.mkv", PATTERNS) == "Movie.2026.mkv"
