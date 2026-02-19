from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TypedDict

_CONFIGURED = False

_DEFAULT_SERVICE = "finance-agent-core"
_DEFAULT_ENV = "dev"
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_LOG_FORMAT = "json"

_CONTEXT_KEYS = (
    "request_id",
    "thread_id",
    "run_id",
    "agent_id",
    "node",
    "ticker",
)

_BASE_RECORD_KEYS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
}
_REDACT_KEYS_DEFAULT = {
    "authorization",
    "cookie",
    "set_cookie",
    "password",
    "token",
    "secret",
    "api_key",
    "x_api_key",
    "openai_api_key",
}


class LogContext(TypedDict, total=False):
    request_id: str
    thread_id: str
    run_id: str
    agent_id: str
    node: str
    ticker: str


_LOG_CONTEXT: contextvars.ContextVar[LogContext | None] = contextvars.ContextVar(
    "log_context",
    default=None,
)


def _normalized_redact_keys() -> set[str]:
    extra = os.getenv("LOG_REDACT_KEYS", "")
    merged = set(_REDACT_KEYS_DEFAULT)
    for key in extra.split(","):
        text = key.strip().lower().replace("-", "_")
        if text:
            merged.add(text)
    return merged


def _normalize_key_name(key: str) -> str:
    return key.strip().lower().replace("-", "_")


_REDACT_KEYS = _normalized_redact_keys()


def _is_sensitive_key(key: str | None) -> bool:
    if key is None:
        return False
    return _normalize_key_name(key) in _REDACT_KEYS


def sanitize_for_logging(value: object, *, key: str | None = None) -> object:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            normalized_key = str(raw_key)
            sanitized[normalized_key] = sanitize_for_logging(
                raw_value, key=normalized_key
            )
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_logging(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_logging(item) for item in value]
    return value


def get_log_context() -> LogContext:
    current = _LOG_CONTEXT.get()
    return dict(current) if current else {}


def bind_log_context(**fields: str | None) -> None:
    context = get_log_context()
    for key, value in fields.items():
        if value is None:
            continue
        text = value.strip()
        if text:
            context[key] = text
    _LOG_CONTEXT.set(context)


def clear_log_context() -> None:
    _LOG_CONTEXT.set({})


@contextmanager
def log_context(**fields: str | None) -> Iterator[None]:
    base = get_log_context()
    merged = dict(base)
    for key, value in fields.items():
        if value is None:
            continue
        text = value.strip()
        if text:
            merged[key] = text
    token = _LOG_CONTEXT.set(merged)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def _extract_extra_fields(record: logging.LogRecord) -> dict[str, object]:
    fields: dict[str, object] = {}
    raw_fields = getattr(record, "fields", None)
    if isinstance(raw_fields, Mapping):
        for key, value in raw_fields.items():
            fields[str(key)] = value
    elif raw_fields is not None:
        fields["fields"] = raw_fields

    for key, value in record.__dict__.items():
        if key in _BASE_RECORD_KEYS:
            continue
        if key in _CONTEXT_KEYS:
            continue
        if key in {"service", "environment", "event", "error_code", "fields"}:
            continue
        fields[key] = value
    return fields


def _format_timestamp(created: float) -> str:
    return datetime.fromtimestamp(created, tz=timezone.utc).isoformat()


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": _format_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "service": getattr(record, "service", _DEFAULT_SERVICE),
            "environment": getattr(record, "environment", _DEFAULT_ENV),
            "message": record.getMessage(),
        }
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if isinstance(value, str) and value:
                payload[key] = value
        event = getattr(record, "event", None)
        if isinstance(event, str) and event:
            payload["event"] = event
        error_code = getattr(record, "error_code", None)
        if isinstance(error_code, str) and error_code:
            payload["error_code"] = error_code

        extra_fields = _extract_extra_fields(record)
        if extra_fields:
            payload["fields"] = sanitize_for_logging(extra_fields)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(
            sanitize_for_logging(payload),
            ensure_ascii=True,
            sort_keys=True,
            default=str,
        )


class _TextLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        parts = [
            _format_timestamp(record.created),
            record.levelname,
            record.name,
            record.getMessage(),
        ]
        event = getattr(record, "event", None)
        if isinstance(event, str) and event:
            parts.append(f"event={event}")
        error_code = getattr(record, "error_code", None)
        if isinstance(error_code, str) and error_code:
            parts.append(f"error_code={error_code}")
        for key in _CONTEXT_KEYS:
            value = getattr(record, key, None)
            if isinstance(value, str) and value:
                parts.append(f"{key}={value}")

        extra_fields = _extract_extra_fields(record)
        if extra_fields:
            encoded_fields = json.dumps(
                sanitize_for_logging(extra_fields),
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            )
            parts.append(f"fields={encoded_fields}")

        if record.exc_info:
            parts.append(f"exception={self.formatException(record.exc_info)}")
        return " ".join(parts)


class _LogContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = get_log_context()
        for key in _CONTEXT_KEYS:
            setattr(record, key, context.get(key))
        record.service = os.getenv("LOG_SERVICE", _DEFAULT_SERVICE)
        record.environment = os.getenv("APP_ENV", _DEFAULT_ENV)
        return True


def _resolve_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", _DEFAULT_LOG_LEVEL).upper()
    resolved = getattr(logging, level_name, logging.INFO)
    return resolved if isinstance(resolved, int) else logging.INFO


def _resolve_formatter() -> logging.Formatter:
    mode = os.getenv("LOG_FORMAT", _DEFAULT_LOG_FORMAT).strip().lower()
    if mode == "text":
        return _TextLogFormatter()
    return _JsonLogFormatter()


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_resolve_formatter())
    handler.addFilter(_LogContextFilter())

    root = logging.getLogger()
    root.setLevel(_resolve_log_level())
    if not root.handlers:
        root.addHandler(handler)
    else:
        for existing in root.handlers:
            existing.addFilter(_LogContextFilter())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    *,
    event: str,
    message: str,
    level: int = logging.INFO,
    error_code: str | None = None,
    fields: Mapping[str, object] | None = None,
) -> None:
    extra: dict[str, object] = {"event": event}
    if error_code is not None:
        extra["error_code"] = error_code
    if fields is not None:
        extra["fields"] = sanitize_for_logging(fields)
    logger.log(level, message, extra=extra)
