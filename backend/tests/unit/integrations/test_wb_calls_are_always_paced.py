"""Nothing may reach WildBerries except through a gated client.

The rate budget is real and small — the settlement endpoint serves about four
requests an hour per token — and it is enforced by a Redis bucket that every
client passes through before an attempt. That enforcement is only as good as its
coverage: one module opening its own HTTP client spends the same budget while
being invisible to the thing that rations it.

That is not hypothetical. On 2026-09-14 a diagnostic script asked WB directly
with `httpx`, took the window the backfill was waiting for, and cost the lane an
hour. The bucket never saw it; WB did, and answered the next caller with a
penalty block.

So the rule is structural: WB's hosts are named in exactly one place, and HTTP
clients against them are built in exactly one package. Both halves matter —
naming the host elsewhere is how a bypass starts, and building a client
elsewhere is how it finishes.
"""

from __future__ import annotations

import pathlib

SRC = pathlib.Path(__file__).resolve().parents[3] / "src"

#: The one package allowed to hold an HTTP client pointed at WB.
INTEGRATION = SRC / "integrations" / "wildberries"

#: The one module allowed to spell the hosts, so they are configurable.
CONFIG = SRC / "core" / "config" / "wildberries.py"


def _python_files() -> list[pathlib.Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_wb_hosts_are_named_in_one_place() -> None:
    """A hard-coded host is a request nobody can redirect, throttle or fake.

    It also silently opts that call out of the settings the test and staging
    environments rely on.
    """
    offenders = [
        str(path.relative_to(SRC))
        for path in _python_files()
        if path != CONFIG
        and INTEGRATION not in path.parents
        and "wildberries.ru" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, f"WB hosts named outside {CONFIG.name}: {offenders}"


def test_only_the_integration_layer_builds_http_clients_for_wb() -> None:
    """Every WB request must pass the rate gate, which lives in the client base.

    A module that constructs its own ``httpx.AsyncClient`` has left the paced
    path. Whether it happens to point at WB today is not the question — the
    budget is shared per token, and a second client is where the next bypass
    comes from.
    """
    # Each exception names a host that is NOT a metered WB API. Adding to this
    # set is a decision about the rate budget, which is why it lives in a test
    # rather than in a reviewer's memory.
    allowed = {
        # HaveIBeenPwned: a different service entirely, with its own limits.
        pathlib.Path("integrations/pwned.py"),
        # The basket CDN — public, unauthenticated, and carrying none of the
        # headers, tokens or gating a WB API client exists to apply.
        pathlib.Path("modules/ab_tests/tasks/passes.py"),
    }
    offenders = [
        str(path.relative_to(SRC))
        for path in _python_files()
        if INTEGRATION not in path.parents
        and path.relative_to(SRC) not in allowed
        and "httpx.AsyncClient(" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        "HTTP clients built outside the integration layer — every WB call must "
        f"pass the rate gate: {offenders}"
    )
