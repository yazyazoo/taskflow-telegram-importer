from __future__ import annotations

from dataclasses import dataclass, field
import re

from taskflow_telegram_importer.errors import ConfigError


@dataclass(frozen=True, slots=True)
class EpisodePattern:
    token_regex: str
    item_regex: str
    token: re.Pattern[str] = field(init=False, repr=False)
    item: re.Pattern[str] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            token = re.compile(self.token_regex)
            item = re.compile(self.item_regex)
        except re.error as exc:
            raise ConfigError("episode pattern expression is invalid") from exc
        if not {"season", "first"}.issubset(token.groupindex):
            raise ConfigError("episode token pattern requires season and first groups")
        if "episode" not in item.groupindex:
            raise ConfigError("episode item pattern requires episode group")
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "item", item)


def normalize_episode_token(
    filename: str, patterns: tuple[EpisodePattern, ...]
) -> str:
    matches = tuple(
        (pattern, match)
        for pattern in patterns
        for match in pattern.token.finditer(filename)
    )
    if len(matches) != 1:
        return filename
    pattern, match = matches[0]
    groups = match.groupdict()
    season = int(groups["season"])
    numbers = [int(groups["first"])]
    repeated = groups.get("repeated")
    if repeated:
        numbers.extend(
            int(item.group("episode")) for item in pattern.item.finditer(repeated)
        )
    elif groups.get("last") is not None:
        last_season = groups.get("last_season")
        if last_season is not None and int(last_season) != season:
            return filename
        final = int(groups["last"])
        if final <= numbers[0]:
            return filename
        numbers = list(range(numbers[0], final + 1))
    token = f"S{season:02d}" + "".join(f"E{number:02d}" for number in numbers)
    return filename[: match.start()] + token + filename[match.end() :]
