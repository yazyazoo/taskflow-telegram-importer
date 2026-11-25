from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from taskflow_telegram_importer.config import ConfigError, load_settings


def _valid_config(tmp_path: Path) -> dict[str, object]:
    return {
        "telegram": {
            "api_id": 123456,
            "api_hash": "telegram-api-hash",
            "bot_token": "123456:telegram-bot-token",
            "session_path": str(tmp_path / "state" / "telegram-importer"),
            "progress_refresh_seconds": 30,
            "max_concurrent_downloads": 2,
            "allowed_user_ids": [123456789, 987654321],
        },
        "taskflow": {"webui_url": "https://taskflow.redprimrose.mov/ui/"},
        "paths": {
            "staging": str(tmp_path / "staging"),
            "gate": str(tmp_path / "gate"),
            "log_file": str(tmp_path / "logs" / "importer.log"),
        },
        "files": {
            "allowed_extensions": ["MKV", ".mp4", "mkv", ".AVI"],
            "minimum_free_gib": 12.5,
        },
        "logging": {"level": "INFO"},
    }


def _write_config(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_load_settings_normalizes_complete_configuration(tmp_path: Path) -> None:
    _write_config(tmp_path, _valid_config(tmp_path))

    settings = load_settings(tmp_path)

    assert settings.telegram.allowed_user_ids == (123456789, 987654321)
    assert settings.telegram.api_id == 123456
    assert settings.telegram.api_hash == "telegram-api-hash"
    assert settings.telegram.bot_token == "123456:telegram-bot-token"
    assert settings.telegram.session_path == (tmp_path / "state" / "telegram-importer").resolve()
    assert settings.telegram.progress_refresh_seconds == 30
    assert settings.telegram.max_concurrent_downloads == 2
    assert settings.taskflow.webui_url == "https://taskflow.redprimrose.mov/ui/"
    assert settings.files.allowed_extensions == (".mkv", ".mp4", ".avi")
    assert settings.files.minimum_free_gib == 12.5
    assert settings.paths.staging == (tmp_path / "staging").resolve()
    assert settings.paths.gate == (tmp_path / "gate").resolve()
    assert settings.logging.level == "INFO"


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda c: c.update({"unexpected": {}}), "unknown"),
        (lambda c: c.pop("files"), "missing"),
        (lambda c: c["telegram"].update({"unexpected": True}), "unknown"),
        (lambda c: c["paths"].pop("gate"), "missing"),
    ],
)
def test_load_settings_rejects_unknown_or_missing_keys(
    tmp_path: Path, mutation, match: str
) -> None:
    config = _valid_config(tmp_path)
    mutation(config)
    _write_config(tmp_path, config)

    with pytest.raises(ConfigError, match=match):
        load_settings(tmp_path)


@pytest.mark.parametrize("invalid_path", ["relative/path", "", "."])
def test_load_settings_rejects_non_absolute_paths(
    tmp_path: Path, invalid_path: str
) -> None:
    config = _valid_config(tmp_path)
    config["paths"]["staging"] = invalid_path
    _write_config(tmp_path, config)

    with pytest.raises(ConfigError, match="absolute"):
        load_settings(tmp_path)


@pytest.mark.parametrize("gate_suffix", ["staging", "staging/gate"])
def test_load_settings_rejects_equal_or_nested_staging_and_gate(
    tmp_path: Path, gate_suffix: str
) -> None:
    config = _valid_config(tmp_path)
    config["paths"]["gate"] = str(tmp_path / gate_suffix)
    _write_config(tmp_path, config)

    with pytest.raises(ConfigError, match="distinct non-nested"):
        load_settings(tmp_path)


def test_load_settings_rejects_gate_parent_of_staging(tmp_path: Path) -> None:
    config = _valid_config(tmp_path)
    config["paths"]["gate"] = str(tmp_path)
    _write_config(tmp_path, config)

    with pytest.raises(ConfigError, match="distinct non-nested"):
        load_settings(tmp_path)


@pytest.mark.parametrize(
    ("section", "field", "value", "match"),
    [
        ("files", "allowed_extensions", [], "extension"),
        ("files", "allowed_extensions", ["."], "extension"),
        ("files", "minimum_free_gib", -1, "minimum_free_gib"),
        ("telegram", "allowed_user_ids", [0], "user ID"),
        ("telegram", "allowed_user_ids", [True], "user ID"),
        ("telegram", "allowed_user_ids", ["123"], "user ID"),
        ("telegram", "api_id", 0, "api_id"),
        ("telegram", "api_id", "123", "api_id"),
        ("telegram", "progress_refresh_seconds", 0, "progress_refresh_seconds"),
        ("telegram", "progress_refresh_seconds", -5, "progress_refresh_seconds"),
        ("telegram", "max_concurrent_downloads", 0, "max_concurrent_downloads"),
        ("telegram", "max_concurrent_downloads", 1.5, "max_concurrent_downloads"),
        ("logging", "level", "TRACE", "logging level"),
    ],
)
def test_load_settings_rejects_invalid_values(
    tmp_path: Path, section: str, field: str, value: object, match: str
) -> None:
    config = _valid_config(tmp_path)
    config[section][field] = value
    _write_config(tmp_path, config)

    with pytest.raises(ConfigError, match=match):
        load_settings(tmp_path)


def test_load_repository_example(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "config.example.yml"
    example = yaml.safe_load(source.read_text(encoding="utf-8"))
    example["paths"] = {
        "staging": str(tmp_path / "staging"),
        "gate": str(tmp_path / "gate"),
        "log_file": str(tmp_path / "logs" / "importer.log"),
    }
    _write_config(tmp_path, example)

    settings = load_settings(tmp_path)

    assert settings.telegram.allowed_user_ids == ()
    assert settings.files.allowed_extensions[0] == ".mkv"
