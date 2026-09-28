"""No route may change anything on a caller who is only allowed to read (P1.x).

An owner can set a manager to read-only. That setting is worth exactly as much
as the weakest write route in the application, and the way it fails is silent:
the route works, the manager sees no error, and the owner believes a limit is in
force that is not. `PATCH /ab-tests/{test_id}` shipped that way on 2026-09-05 —
a read-only manager could retune a running test's rotation trigger, and lowering
a budget below what the live photo has already gathered swaps the card's main
photo on the very next poll.

**Why this is derived rather than listed.** The module-scoped test that was
supposed to catch it enumerated its five paths by hand, and a hand-written list
only ever proves the routes someone remembered. This walks the real app's
routers and resolves each route's whole dependency tree, so a new route is
covered the moment it exists — the same shape as
``test_every_covered_route_binds_a_tenant.py``, for a different invariant.

**What it cannot do.** It proves a guard is *present*, never that it is the
*right* one: a route needing owner-only that settles for writer passes here. The
`security` skill's checklist is still what decides which guard a route deserves;
this only makes "nobody remembered any guard" impossible to ship.

**Why the method is the trigger.** POST/PATCH/PUT/DELETE is a proxy for "changes
something", and a proxy has both kinds of error. A POST-shaped read (a preview
computed from a body) is a false positive and is exempted below with its reason;
a GET that writes would be a false negative, which no list can catch and which
review has to. Defaulting to "every mutating verb answers for itself" puts the
work on the exception rather than on remembering the rule.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from fastapi.routing import APIRoute, iter_route_contexts

from src.modules.organizations.deps import require_dev, require_owner, require_writer
from src.modules.users.deps import require_dev_role

#: Any of these is at least as strong as "may write". A dev-only or owner-only
#: route is not missing a writer check — it demands more than one.
_WRITE_GUARDS = {require_writer, require_owner, require_dev, require_dev_role}

#: Verbs treated as changing something.
_MUTATING = {"POST", "PATCH", "PUT", "DELETE"}

#: Mutating routes that legitimately resolve no write guard. Every entry is one
#: of three kinds, and the kind is the justification:
#:
#: * **Pre-membership.** The caller has no organisation yet — they are signing
#:   in, proving an email, redeeming an invitation. A membership-derived guard
#:   has nothing to read, and requiring one would lock the door from inside.
#: * **Acts only on the caller's own session.** Logging out, refreshing,
#:   revoking one's own sessions: the authorisation is the token itself.
#: * **A POST that reads.** A preview computed from a body changes nothing, and
#:   a read-only manager is entitled to it.
_EXEMPT: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/register"): "pre-membership: creates the account",
    ("POST", "/api/v1/auth/login"): "pre-membership: establishes the session",
    ("POST", "/api/v1/auth/refresh"): "own session: authorised by the refresh cookie",
    ("POST", "/api/v1/auth/logout"): "own session: ends it",
    ("POST", "/api/v1/auth/logout-all"): "own session: ends every one of them",
    ("DELETE", "/api/v1/auth/sessions/{family_id}"): "own session: ends one named lineage",
    (
        "POST",
        "/api/v1/auth/password",
    ): "own account: authorised by the current password in the body, not by membership",
    ("POST", "/api/v1/auth/confirm-email"): "pre-membership: proves the address",
    ("POST", "/api/v1/auth/resend-confirmation"): "pre-membership: re-sends that proof",
    ("POST", "/api/v1/auth/password-reset/request"): "pre-membership: unauthenticated by design",
    ("POST", "/api/v1/auth/password-reset/confirm"): "pre-membership: redeems the reset token",
    ("POST", "/api/v1/organizations/activate"): "pre-membership: redeems an activation code",
    ("POST", "/api/v1/organizations/invitations/accept"): "pre-membership: joins an organisation",
    (
        "POST",
        "/api/v1/monitoring/skus/{nm_id}/matrix/preview",
    ): "a POST that reads: previews a matrix from a body, writes nothing",
}


class _Route(NamedTuple):
    """One API route as a request meets it."""

    path: str
    methods: set[str]
    dependant: Any


def _api_routes(routes: Any) -> list[_Route]:
    """Every API route as the server resolves it: full path, full dependency tree.

    FastAPI defers router inclusion behind a wrapper, so a plain pass over
    ``app.routes`` finds only ``/health`` — which would make every assertion
    below pass while checking nothing. Following ``original_router.routes`` by
    hand is no better: a sub-router's routes come back without the prefixes
    they were included under (``/weeks`` for ``/api/v1/finreports/weeks``), and
    without the ``dependencies=`` passed to ``include_router``. That walk
    silently dropped every finreports and monitoring sub-router from the check.
    ``iter_route_contexts`` is the iterator the OpenAPI schema is built from, so
    it sees exactly the routes and dependencies a request does.
    """
    found: list[_Route] = []
    for ctx in iter_route_contexts(routes):
        if isinstance(ctx.original_route, APIRoute):
            # Optional only because a context may also wrap a mount or a websocket.
            assert ctx.path is not None
            assert ctx.methods is not None
            found.append(_Route(ctx.path, ctx.methods, ctx.dependant))
    return found


def _dependency_tree(dependant: Any, seen: set[Any] | None = None) -> set[Any]:
    """Every callable FastAPI would resolve for one route."""
    seen = seen if seen is not None else set()
    if dependant.call is not None:
        seen.add(dependant.call)
    for sub in dependant.dependencies:
        _dependency_tree(sub, seen)
    return seen


def _mutating_routes(routes: list[_Route]) -> list[tuple[str, str, _Route]]:
    """Every (verb, path, route) that changes something."""
    found = []
    for route in routes:
        for method in sorted((route.methods - {"HEAD", "OPTIONS"}) & _MUTATING):
            found.append((method, route.path, route))
    return found


def test_every_mutating_route_demands_more_than_membership() -> None:
    """A read-only manager must not be able to reach any writing route."""
    # Arrange
    from main import app

    routes = _api_routes(app.routes)
    mutating = _mutating_routes(routes)
    assert len(mutating) > 20, "the route walk is broken, not the app — this would pass vacuously"

    # Act
    unguarded = [
        f"{method} {path}"
        for method, path, route in mutating
        if (method, path) not in _EXEMPT and not _dependency_tree(route.dependant) & _WRITE_GUARDS
    ]

    # Assert
    assert unguarded == [], (
        "these routes change something but ask for nothing more than membership — "
        "add WritingAccess (or a stronger guard), or exempt them with a reason: "
        f"{unguarded}"
    )


def test_the_exemptions_still_exist() -> None:
    """An exemption for a route that is gone hides the next one worth looking at.

    Without this the list only ever grows, and a stale entry silently pre-approves
    whatever later takes that path.
    """
    # Arrange
    from main import app

    live = {(method, path) for method, path, _ in _mutating_routes(_api_routes(app.routes))}

    # Assert
    stale = set(_EXEMPT) - live
    assert not stale, f"exemption names a route that no longer exists: {stale}"
