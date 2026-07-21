"""Shared plumbing for the monitoring Celery tasks (retry policy, resilience)."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from src.core.exceptions import IntegrationError
from src.core.logging import get_logger

logger = get_logger(__name__)

#: Shared retry policy for the harvest tasks: transient WB/DB failures are
#: retried with exponential backoff instead of silently producing a
#: zero-row "success".
_TASK_RETRY_KWARGS: dict[str, object] = {
    "autoretry_for": (IntegrationError, OperationalError),
    "max_retries": 3,
    "retry_backoff": 120,  # 2 min, 4 min, 8 min
    "retry_backoff_max": 900,
    "retry_jitter": True,
}


def _unwrap[T](result: T | BaseException | None, label: str) -> T | None:
    """Return a gathered result, or ``None`` if that WB source raised.

    Used with ``asyncio.gather(return_exceptions=True)`` so one failed source
    is logged and skipped instead of aborting the whole harvest.

    Args:
        result: The value the source produced, an exception it raised, or
            ``None`` when the source was not requested.
        label: Human-readable source name for the log line.

    Returns:
        The successful value, or ``None`` on failure/absence.
    """
    if isinstance(result, BaseException):
        logger.warning("Harvest source '%s' failed and was skipped: %s", label, result)
        return None
    return result
