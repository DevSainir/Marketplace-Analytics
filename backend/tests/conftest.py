"""Root pytest configuration shared by every backend tier.

Responsibilities kept deliberately narrow:

* **Tier auto-marking** — a test's directory *is* its speed tier, so nobody has
  to remember ``@pytest.mark.integration``. ``tests/unit/**`` gets ``unit``,
  ``tests/component/**`` gets ``component``, ``tests/integration/**`` gets
  ``integration``. CI and local runs then select with ``-m``.
* **Settings isolation** — :data:`src.core.config.settings` is a process-wide
  singleton read from ``backend/.env``. A test that mutates it would leak into
  every later test, so :func:`settings_override` restores the previous value.

Tier-specific machinery (the ASGI client, the real database) lives in the
``conftest.py`` of the tier that needs it — importing a Postgres fixture into a
unit run would defeat the point of the pyramid.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

#: Directory name under ``tests/`` -> the marker applied to everything inside.
_TIER_MARKERS: dict[str, str] = {
    "unit": "unit",
    "component": "component",
    "integration": "integration",
}

_TESTS_ROOT = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Tag every collected test with the marker of the tier it lives in.

    Args:
        items: The collected test items, mutated in place.
    """
    for item in items:
        try:
            relative = Path(str(item.fspath)).relative_to(_TESTS_ROOT)
        except ValueError:  # a test collected from outside tests/ — leave it be
            continue
        tier = relative.parts[0] if relative.parts else ""
        marker = _TIER_MARKERS.get(tier)
        if marker is not None:
            item.add_marker(marker)


@pytest.fixture(scope="session", autouse=True)
def _cheap_password_hashing() -> Iterator[None]:
    """Drop the bcrypt work factor to its minimum for the whole test session.

    Production uses 2**12 rounds, which costs ~250 ms per hash *by design*.
    Paying that in a unit tier turns a sub-second suite into a ten-second one
    and pushes people towards not running it. The rounds are a cost parameter,
    not part of the behaviour under test — every property the tests assert
    (salting, verification, the 72-byte ceiling, digest format) is identical at
    4 rounds. The value that ships is pinned by
    ``tests/unit/core/test_password_hashing.py`` reading the real constant.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("src.core.security._BCRYPT_ROUNDS", 4)
        yield


@pytest.fixture(scope="session", autouse=True)
def _no_outbound_breach_check() -> Iterator[None]:
    """Keep the Have I Been Pwned lookup out of every tier by default.

    Registration consults HIBP's range API, which is a real outbound HTTPS call
    to a third party. A test suite that made it would be neither hermetic nor
    fast, and would fail on an aeroplane. The setting makes the check a no-op
    rather than an error, so the registration path still runs end to end — the
    check's own behaviour is covered directly in
    ``tests/unit/users/test_password_breach_check.py`` against a stubbed
    transport, and the service's reaction to a positive answer with an injected
    fake.
    """
    from src.core.config import settings

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(settings, "password_breach_check_enabled", False)
        yield


@pytest.fixture
def settings_override() -> Iterator[Any]:
    """Yield a context manager that patches settings fields and restores them.

    The application settings object is a module-level singleton, so an
    unrestored mutation silently changes behaviour for every subsequent test in
    the session (test order then decides the result). Usage::

        def test_x(settings_override):
            with settings_override(access_token_ttl_seconds=1):
                ...

    Yields:
        A context manager accepting ``**field=value`` overrides.
    """
    from src.core.config import settings

    @contextmanager
    def _override(**values: Any) -> Iterator[None]:
        previous = {field: getattr(settings, field) for field in values}
        for field, value in values.items():
            setattr(settings, field, value)
        try:
            yield
        finally:
            for field, value in previous.items():
                setattr(settings, field, value)

    return _override
