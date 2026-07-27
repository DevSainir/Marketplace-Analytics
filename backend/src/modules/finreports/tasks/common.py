"""Shared retry policy for the finreports Celery tasks."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from src.core.exceptions import IntegrationError

#: Transient WB/DB failures are retried with exponential backoff instead of
#: silently producing a zero-row "success".
_TASK_RETRY_KWARGS: dict[str, object] = {
    "autoretry_for": (IntegrationError, OperationalError),
    "max_retries": 3,
    "retry_backoff": 120,
    "retry_backoff_max": 900,
    "retry_jitter": True,
}
