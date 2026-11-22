from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from .errors import ConfigError


@dataclass(frozen=True, slots=True)
class SecretCommand:
    executable: Path
    alias: str
    field: str


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    api_base_url: str
    local_mode: bool
    long_poll_request_timeout_seconds: float
    allowed_user_ids: tuple[int, ...]
    token_command: SecretCommand


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
class Settings:
    telegram: TelegramSettings
    paths: PathSettings
    files: FileSettings
    logging: LoggingSettings


_ROOT_KEYS = {"telegram", "paths", "files", "logging"}
_TELEGRAM_KEYS = {
    "api_base_url",
    "local_mode",
    "long_poll_request_timeout_seconds",
    "allowed_user_ids",
    "token_command",
}
_SECRET_KEYS = {"executable", "alias", "field"}
_PATH_KEYS = {"staging", "gate", "log_file"}
_FILE_KEYS = {"allowed_extensions", "minimum_free_gib"}
_LOGGING_KEYS = {"level"}
_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


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
    secret_raw = _mapping(telegram_raw["token_command"], "telegram.token_command")
    _require_exact_keys(secret_raw, _SECRET_KEYS, "telegram.token_command")

    paths_raw = _mapping(root["paths"], "paths")
    _require_exact_keys(paths_raw, _PATH_KEYS, "paths")
    files_raw = _mapping(root["files"], "files")
    _require_exact_keys(files_raw, _FILE_KEYS, "files")
    logging_raw = _mapping(root["logging"], "logging")
    _require_exact_keys(logging_raw, _LOGGING_KEYS, "logging")

    telegram = TelegramSettings(
        api_base_url=_nonempty_string(telegram_raw["api_base_url"], "api_base_url"),
        local_mode=_boolean(telegram_raw["local_mode"], "local_mode"),
        long_poll_request_timeout_seconds=_positive_number(
            telegram_raw["long_poll_request_timeout_seconds"], "timeout"
        ),
        allowed_user_ids=_user_ids(telegram_raw["allowed_user_ids"]),
        token_command=SecretCommand(
            executable=_absolute_path(secret_raw["executable"], "secret executable"),
            alias=_nonempty_string(secret_raw["alias"], "secret alias"),
            field=_nonempty_string(secret_raw["field"], "secret field"),
        ),
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
        paths=paths,
        files=FileSettings(
            allowed_extensions=_extensions(files_raw["allowed_extensions"]),
            minimum_free_gib=minimum_free_gib,
        ),
        logging=LoggingSettings(level=level),
    )


def resolve_secret(command: SecretCommand) -> str:
    try:
        result = subprocess.run(
            [str(command.executable), command.alias, command.field],
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
    except OSError as exc:
        raise ConfigError("secret command could not be executed") from exc

    if result.returncode != 0:
        raise ConfigError("secret command failed")
    value = result.stdout.rstrip("\r\n")
    if not value:
        raise ConfigError("secret command returned an empty value")
    return value


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


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be boolean")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be numeric")
    return float(value)


def _positive_number(value: Any, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return number


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
