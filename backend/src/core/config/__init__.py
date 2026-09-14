"""Application configuration loaded from the environment.

Settings are parsed once at import time into a cached :class:`Settings`
singleton so that every layer (API process, Celery worker, Alembic) reads an
identical, fully-validated configuration object.

The configuration is split by responsibility, one module per area:

* :mod:`~src.core.config.app` — service identity, environment, logging.
* :mod:`~src.core.config.datastore` — PostgreSQL and Redis, and the DSNs
  derived from them.
* :mod:`~src.core.config.security` — JWT, the refresh cookie, registration and
  abuse throttles, CORS, token encryption.
* :mod:`~src.core.config.wildberries` — the WB seller APIs: hosts, transport
  budget, client-side rate buckets.
* :mod:`~src.core.config.storefront` — the public, unauthenticated WB card and
  search endpoints.
* :mod:`~src.core.config.guide` — bounds on the reference capture, which
  must never cost the paying harvests a worker slot.
* :mod:`~src.core.config.observability` — Prometheus exposition, Sentry
  reporting, and log rotation.
* :mod:`~src.core.config.assembly` — composes all of the above into
  :class:`Settings` and enforces the cross-section production hardening.

This ``__init__`` is the package's facade: every consumer imports
``Settings``, ``get_settings`` or ``settings`` from ``src.core.config`` and is
insulated from the layout above.
"""

from src.core.config.app import Environment
from src.core.config.assembly import Settings, get_settings, settings

__all__ = [
    "Environment",
    "Settings",
    "get_settings",
    "settings",
]
