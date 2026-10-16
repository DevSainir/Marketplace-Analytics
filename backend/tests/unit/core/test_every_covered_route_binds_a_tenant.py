"""No route may reach a policy-covered table without binding a tenant (P2.5).

Row-level security fails **closed and loud**: a query that arrives with no
workspace bound raises rather than returning fewer rows. That is the right
behaviour, and it makes an unbound route a 500 on a customer's screen rather
than a quiet leak — so the check worth having *before* those policies are
applied is "does every route that touches a covered table go through a binder".

The answer has to come from the dependency graph, not from reading routers.
Grepping is what missed `workspaces.workspace_tokens` the first time: its
owner-only routes take the workspace from the URL path rather than the header,
so they matched no search for the header dependency and would have raised on
every token screen the moment the policies were applied.

This walks the real app. For every route in a module owning at least one table
in `scripts/sql/row_level_security.sql`, it resolves the whole dependency tree
and looks for either binder. Exemptions are listed by name, so a route that
needs one is a decision somebody makes rather than an omission nobody sees.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from fastapi.routing import APIRoute, iter_route_contexts

from src.modules.workspaces.deps import (
    get_current_workspace_id,
    get_member_path_workspace_id,
    get_path_workspace_id,
)

#: Each of these validates the workspace against the caller's organisation and
#: then binds it to the transaction: the header, the owner's path and a member's
#: path. There is no fourth way to bind one.
_BINDERS = {get_current_workspace_id, get_path_workspace_id, get_member_path_workspace_id}

#: Modules owning at least one table in the policy list, plus `summary`, which
#: owns none but reads finreports' and monitoring's covered tables through their
#: contracts — a path filter keyed on owners alone would never look at it.
#: `heatmap` qualifies twice over: it owns two covered tables and reads both
#: other modules' through their contracts.
_COVERED_MODULES = (
    "monitoring",
    "finreports",
    "ab-tests",
    "workspaces",
    "summary",
    "heatmap",
    "advertising",
)

#: Routes in those modules that legitimately bind nothing, because they touch no
#: covered table. Both read `workspaces.workspaces`, which carries
#: `organization_id` rather than `workspace_id` and is deliberately outside the
#: policy set — a workspace *list* cannot be scoped to one workspace.
#: The four `/guests` routes are the dev's grant screen: they read and write
#: `workspaces.workspace_guests` (and list `workspaces.workspaces` by name), both
#: outside the policy set for the same reason — they decide which workspace may
#: be bound, so they are read before one is.
_EXEMPT = {
    ("GET", "/api/v1/workspaces"),
    ("POST", "/api/v1/workspaces"),
    ("GET", "/api/v1/workspaces/guests"),
    ("GET", "/api/v1/workspaces/guests/workspaces"),
    ("POST", "/api/v1/workspaces/guests"),
    ("DELETE", "/api/v1/workspaces/guests/{grant_id}"),
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


def test_every_route_touching_a_covered_module_binds_a_tenant() -> None:
    """The automated form of "walk every router before adding a table"."""
    # Arrange
    from main import app

    routes = _api_routes(app.routes)
    assert len(routes) > 20, "the route walk is broken, not the app — this would pass vacuously"

    # Act
    unbound = []
    for route in routes:
        if not any(f"/{module}" in route.path for module in _COVERED_MODULES):
            continue
        method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
        if (method, route.path) in _EXEMPT:
            continue
        if not _dependency_tree(route.dependant) & _BINDERS:
            unbound.append(f"{method} {route.path}")

    # Assert
    assert unbound == [], (
        "these routes would raise once row-level security is applied — resolve their "
        f"workspace through CurrentWorkspaceId or a path binder: {unbound}"
    )


def test_the_exemptions_still_exist() -> None:
    """An exemption for a route that is gone hides the next one worth looking at."""
    # Arrange
    from main import app

    live = {(sorted(r.methods - {"HEAD", "OPTIONS"})[0], r.path) for r in _api_routes(app.routes)}

    # Assert
    assert live >= _EXEMPT, f"exemption names a route that no longer exists: {_EXEMPT - live}"
