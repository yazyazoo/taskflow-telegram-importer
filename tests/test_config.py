from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
import yaml

from taskflow_telegram_importer.config import (
    ConfigError,
    SecretCommand,
    load_settings,
    resolve_secret,
)


def _valid_config(tmp_path: Path) -> dict[str, object]:
    return {
        "telegram": {
            "api_base_url": "http://127.0.0.1:8081/bot",
            "local_mode": True,
            "long_poll_request_timeout_seconds": 30,
            "allowed_user_ids": [123456789, 987654321],
            "token_command": {
                "executable": "/mnt/shared/Personal/bin/rp-secret",
                "alias": "taskflow_telegram_importer",
                "field": "token",
            },
        },
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
    assert settings.telegram.long_poll_request_timeout_seconds == 30
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
        ("telegram", "long_poll_request_timeout_seconds", 0, "timeout"),
        ("telegram", "long_poll_request_timeout_seconds", -5, "timeout"),
        ("telegram", "local_mode", False, "local_mode"),
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


def _write_executable(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "secret-command"
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o700)
    return path


def test_resolve_secret_executes_direct_arguments_and_trims_output(tmp_path: Path) -> None:
    executable = _write_executable(
        tmp_path,
        '[ "$1" = "alias-name" ] && [ "$2" = "token" ] || exit 7\nprintf "resolved-secret\\n"',
    )

    result = resolve_secret(SecretCommand(executable, "alias-name", "token"))

    assert result == "resolved-secret"


@pytest.mark.parametrize(
    "body",
    [
        'printf "super-secret" >&2; exit 9',
        'printf ""',
        'printf "\\n\\n"',
    ],
)
def test_resolve_secret_rejects_failure_or_empty_output_without_leaking(
    tmp_path: Path, body: str, caplog: pytest.LogCaptureFixture
) -> None:
    executable = _write_executable(tmp_path, body)
    caplog.set_level(logging.DEBUG)

    with pytest.raises(ConfigError) as raised:
        resolve_secret(SecretCommand(executable, "alias-name", "token"))

    combined = f"{raised.value}\n{caplog.text}"
    assert "super-secret" not in combined


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
