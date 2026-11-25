from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ConfigError
from .filenames import EpisodePattern


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    api_id: int
    api_hash: str
    bot_token: str
    session_path: Path
    progress_refresh_seconds: float
    max_concurrent_downloads: int
    allowed_user_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class PathSettings:
    staging: Path
    gate: Path
    log_file: Path


@dataclass(frozen=True, slots=True)
class FileSettings:
    allowed_extensions: tuple[str, ...]
    minimum_free_gib: float


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    level: str


@dataclass(frozen=True, slots=True)
class TaskFlowSettings:
    webui_url: str
    api_base_url: str
    api_token: str
    filesystem_integration_code: str
    request_timeout_seconds: float
    reconciliation_poll_seconds: float
    reconciliation_timeout_seconds: float


@dataclass(frozen=True, slots=True)
class TmdbSettings:
    api_base_url: str
    api_key: str
    language: str
    request_timeout_seconds: float
    max_results: int


@dataclass(frozen=True, slots=True)
class Settings:
    telegram: TelegramSettings
    taskflow: TaskFlowSettings
    tmdb: TmdbSettings
    paths: PathSettings
    files: FileSettings
    logging: LoggingSettings
    episode_patterns: tuple[EpisodePattern, ...]


_ROOT_KEYS = {
    "telegram", "taskflow", "tmdb", "paths", "files", "logging", "episode_patterns"
}
_TELEGRAM_KEYS = {
    "api_id",
    "api_hash",
    "bot_token",
    "session_path",
    "progress_refresh_seconds",
    "max_concurrent_downloads",
    "allowed_user_ids",
}
_PATH_KEYS = {"staging", "gate", "log_file"}
_FILE_KEYS = {"allowed_extensions", "minimum_free_gib"}
_LOGGING_KEYS = {"level"}
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_TASKFLOW_KEYS = {
    "webui_url", "api_base_url", "api_token", "filesystem_integration_code",
    "request_timeout_seconds", "reconciliation_poll_seconds",
    "reconciliation_timeout_seconds",
}
_TMDB_KEYS = {
    "api_base_url", "api_key", "language", "request_timeout_seconds", "max_results"
}


def load_settings(project_root: Path) -> Settings:
    config_path = Path(project_root) / "config.yml"
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"could not read configuration: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError("configuration is not valid YAML") from exc

    root = _mapping(raw, "configuration")
    _require_exact_keys(root, _ROOT_KEYS, "configuration")

    telegram_raw = _mapping(root["telegram"], "telegram")
    _require_exact_keys(telegram_raw, _TELEGRAM_KEYS, "telegram")
    taskflow_raw = _mapping(root["taskflow"], "taskflow")
    _require_exact_keys(taskflow_raw, _TASKFLOW_KEYS, "taskflow")
    tmdb_raw = _mapping(root["tmdb"], "tmdb")
    _require_exact_keys(tmdb_raw, _TMDB_KEYS, "tmdb")

    paths_raw = _mapping(root["paths"], "paths")
    _require_exact_keys(paths_raw, _PATH_KEYS, "paths")
    files_raw = _mapping(root["files"], "files")
    _require_exact_keys(files_raw, _FILE_KEYS, "files")
    logging_raw = _mapping(root["logging"], "logging")
    _require_exact_keys(logging_raw, _LOGGING_KEYS, "logging")

    telegram = TelegramSettings(
        api_id=_positive_integer(telegram_raw["api_id"], "api_id"),
        api_hash=_nonempty_string(telegram_raw["api_hash"], "api_hash"),
        bot_token=_nonempty_string(telegram_raw["bot_token"], "bot_token"),
        session_path=_absolute_path(telegram_raw["session_path"], "session_path"),
        progress_refresh_seconds=_positive_number(
            telegram_raw["progress_refresh_seconds"], "progress_refresh_seconds"
        ),
        max_concurrent_downloads=_positive_integer(
            telegram_raw["max_concurrent_downloads"], "max_concurrent_downloads"
        ),
        allowed_user_ids=_user_ids(telegram_raw["allowed_user_ids"]),
    )

    paths = PathSettings(
        staging=_absolute_path(paths_raw["staging"], "staging"),
        gate=_absolute_path(paths_raw["gate"], "gate"),
        log_file=_absolute_path(paths_raw["log_file"], "log_file"),
    )
    _validate_non_nested(paths.staging, paths.gate)

    minimum_free_gib = _number(files_raw["minimum_free_gib"], "minimum_free_gib")
    if minimum_free_gib < 0:
        raise ConfigError("minimum_free_gib must be zero or greater")

    level = _nonempty_string(logging_raw["level"], "logging level").upper()
    if level not in _LOG_LEVELS:
        raise ConfigError(f"logging level must be one of {sorted(_LOG_LEVELS)}")

    return Settings(
        telegram=telegram,
        taskflow=TaskFlowSettings(
            webui_url=_https_url(taskflow_raw["webui_url"], "taskflow.webui_url"),
            api_base_url=_http_url(taskflow_raw["api_base_url"], "taskflow.api_base_url"),
            api_token=_nonempty_string(taskflow_raw["api_token"], "taskflow.api_token"),
            filesystem_integration_code=_nonempty_string(
                taskflow_raw["filesystem_integration_code"],
                "taskflow.filesystem_integration_code",
            ),
            request_timeout_seconds=_positive_number(
                taskflow_raw["request_timeout_seconds"], "taskflow.request_timeout_seconds"
            ),
            reconciliation_poll_seconds=_positive_number(
                taskflow_raw["reconciliation_poll_seconds"],
                "taskflow.reconciliation_poll_seconds",
            ),
            reconciliation_timeout_seconds=_positive_number(
                taskflow_raw["reconciliation_timeout_seconds"],
                "taskflow.reconciliation_timeout_seconds",
            ),
        ),
        tmdb=TmdbSettings(
            api_base_url=_http_url(tmdb_raw["api_base_url"], "tmdb.api_base_url"),
            api_key=_nonempty_string(tmdb_raw["api_key"], "tmdb.api_key"),
            language=_nonempty_string(tmdb_raw["language"], "tmdb.language"),
            request_timeout_seconds=_positive_number(
                tmdb_raw["request_timeout_seconds"], "tmdb.request_timeout_seconds"
            ),
            max_results=_positive_integer(tmdb_raw["max_results"], "tmdb.max_results"),
        ),
        paths=paths,
        files=FileSettings(
            allowed_extensions=_extensions(files_raw["allowed_extensions"]),
            minimum_free_gib=minimum_free_gib,
        ),
        logging=LoggingSettings(level=level),
        episode_patterns=_episode_patterns(root["episode_patterns"]),
    )


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: set[str], name: str
) -> None:
    missing = expected - value.keys()
    unknown = value.keys() - expected
    if missing:
        raise ConfigError(f"{name} has missing keys: {', '.join(sorted(missing))}")
    if unknown:
        raise ConfigError(f"{name} has unknown keys: {', '.join(sorted(unknown))}")


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    return value.strip()


def _https_url(value: Any, name: str) -> str:
    text = _nonempty_string(value, name)
    if not text.startswith("https://"):
        raise ConfigError(f"{name} must be an HTTPS URL")
    return text


def _http_url(value: Any, name: str) -> str:
    text = _nonempty_string(value, name).rstrip("/")
    if not text.startswith(("http://", "https://")):
        raise ConfigError(f"{name} must be an HTTP or HTTPS URL")
    return text


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be numeric")
    return float(value)


def _positive_number(value: Any, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return number


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{name} must be a positive integer")
    return value


def _absolute_path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} path must be absolute")
    text = value.strip()
    path = Path(text)
    if not path.is_absolute():
        raise ConfigError(f"{name} path must be absolute")
    return path.resolve(strict=False)


def _validate_non_nested(staging: Path, gate: Path) -> None:
    if staging == gate or staging in gate.parents or gate in staging.parents:
        raise ConfigError("staging and gate must be distinct non-nested paths")


def _user_ids(value: Any) -> tuple[int, ...]:
    if not isinstance(value, list):
        raise ConfigError("allowed_user_ids must be a list")
    result: list[int] = []
    for user_id in value:
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ConfigError("every Telegram user ID must be a positive integer")
        if user_id not in result:
            result.append(user_id)
    return tuple(result)


def _extensions(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("allowed_extensions must contain at least one extension")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ConfigError("every extension must be a string")
        extension = item.strip().lower()
        if not extension.startswith("."):
            extension = f".{extension}"
        if extension == "." or "/" in extension or "\\" in extension:
            raise ConfigError("every extension must be a simple file extension")
        if extension not in result:
            result.append(extension)
    return tuple(result)


def _episode_patterns(value: Any) -> tuple[EpisodePattern, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError("episode_patterns must contain at least one pattern")
    result = []
    for item in value:
        mapping = _mapping(item, "episode pattern")
        _require_exact_keys(mapping, {"token_regex", "item_regex"}, "episode pattern")
        result.append(EpisodePattern(
            _nonempty_string(mapping["token_regex"], "episode token_regex"),
            _nonempty_string(mapping["item_regex"], "episode item_regex"),
        ))
    return tuple(result)
