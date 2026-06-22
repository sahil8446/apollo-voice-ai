"""Structured JSON logging.

Voice is latency-sensitive, so every request logs a `latency_ms` field and a
`request_id` that ties the FastAPI request, the Retell tool call, and any DB
work together. In prod these JSON lines ship straight to a log aggregator.
"""

from __future__ import annotations

import logging
import sys

try:  # python-json-logger >= 3.1 moved the formatter to .json
    from pythonjsonlogger.json import JsonFormatter
except ImportError:  # pragma: no cover - older versions
    from pythonjsonlogger.jsonlogger import JsonFormatter


def configure_logging(level: str = "INFO", *, json_format: bool = True) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        formatter = JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
            timestamp=True,
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s  %(levelname)-7s  %(name)s  %(message)s"
        )
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Quiet noisy libraries; we keep our own request logs.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
