from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class SecretRedactionFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(value for value in secrets if value)

    def filter(self, record: logging.LogRecord) -> bool:
        rendered = record.getMessage()
        for secret in self._secrets:
            rendered = rendered.replace(secret, "[REDACTED]")
        record.msg = rendered
        record.args = ()
        return True


@dataclass(slots=True)
class LoggingController:
    logger: logging.Logger
    handlers: tuple[logging.Handler, ...]

    def close(self) -> None:
        for handler in self.handlers:
            self.logger.removeHandler(handler)
            handler.close()


def configure_logging(
    level: str, log_file: Path, *, secrets: Iterable[str] = ()
) -> LoggingController:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("taskflow_telegram_importer")
    logger.setLevel(level)
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    redaction = SecretRedactionFilter(secrets)
    stream = logging.StreamHandler()
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    for handler in (stream, file_handler):
        handler.setLevel(level)
        handler.setFormatter(formatter)
        handler.addFilter(redaction)
        logger.addHandler(handler)
    return LoggingController(logger, (stream, file_handler))
