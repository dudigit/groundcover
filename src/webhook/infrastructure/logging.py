"""Structlog configuration for production-grade structured JSON logging.

Processor chain (in order):
  add_log_level → add_timestamp → bind_contextvars → sanitize_sensitive_fields → JSONRenderer

Key decisions:
- One JSON object per line — compatible with Datadog, Loki, CloudWatch.
- `request_id` and `trace_id` are bound via contextvars at request start, not passed around.
- Sanitizer strips object/oldObject bodies and userInfo.extra — prevents PII/secret leakage.
- Log sampling applies only to INFO success events (configurable rate).
"""

import random
import sys
from collections.abc import Callable

import structlog
from structlog.types import EventDict, WrappedLogger

# Fields stripped entirely from every log event — never log K8s object bodies or token data
_SENSITIVE_FIELDS: frozenset[str] = frozenset({"object", "oldObject", "extra", "groups"})

# Max length for any single string value — long values are truncated with a marker
_MAX_STRING_LENGTH = 200


def _sanitize_sensitive_fields(
    _logger: WrappedLogger,
    _method: str,
    event_dict: EventDict,
) -> EventDict:
    """Strip sensitive fields and truncate oversized strings."""
    for key in _SENSITIVE_FIELDS:
        event_dict.pop(key, None)

    for key, value in list(event_dict.items()):
        if isinstance(value, str) and len(value) > _MAX_STRING_LENGTH:
            event_dict[key] = f"<truncated:{len(value)}>"

    return event_dict


def _make_sampling_processor(
    sample_rate: float,
) -> Callable[[WrappedLogger, str, EventDict], EventDict]:
    """Return a processor that drops INFO success events based on sample_rate.

    Events at WARNING or above, and any error events, are never dropped.
    """

    def _sample(
        _logger: WrappedLogger,
        method: str,
        event_dict: EventDict,
    ) -> EventDict:
        # Only sample INFO-level success events
        if method != "info":
            return event_dict
        event = event_dict.get("event", "")
        if (
            event == "admission.mutation.complete"
            and sample_rate < 1.0
            and random.random() > sample_rate  # not security-sensitive sampling
        ):
            raise structlog.DropEvent
        return event_dict

    return _sample


def configure_logging(log_level: str = "INFO", sample_rate: float = 1.0) -> None:
    """Configure structlog for the application.

    Call once at application startup (inside lifespan).
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _sanitize_sensitive_fields,
            _make_sampling_processor(sample_rate),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(__import__("logging"), log_level, 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def bind_request_context(request_id: str, trace_id: str | None = None) -> None:
    """Bind request-scoped context variables.

    All log calls within the same async task will automatically carry these fields.
    Call `clear_request_context()` in a finally block after each request.
    """
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        **({} if trace_id is None else {"trace_id": trace_id}),
    )


def clear_request_context() -> None:
    """Clear all contextvars — must be called after every request to prevent leaks."""
    structlog.contextvars.clear_contextvars()
