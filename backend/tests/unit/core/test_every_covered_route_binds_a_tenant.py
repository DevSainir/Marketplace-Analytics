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

from typing import Any

from fastapi.routing import APIRoute

from src.modules.workspaces.deps import get_current_workspace_id, get_path_workspace_id

#: Either of these validates the workspace against the caller's organisation and
#: then binds it to the transaction. There is no third way to bind one.
_BINDERS = {get_current_workspace_id, get_path_workspace_id}

#: Modules owning at least one table in the policy list.
_COVERED_MODULES = ("monitoring", "finreports", "ab-tests", "workspaces")

#: Routes in those modules that legitimately bind nothing, because they touch no
#: covered table. Both read `workspaces.workspaces`, which carries
#: `organization_id` rather than `workspace_id` and is deliberately outside the
#: policy set — a workspace *list* cannot be scoped to one workspace.
#: The three `/guests` routes are the dev's grant screen: they read and write
#: `workspaces.workspace_guests`, which is outside the policy set for the same
#: reason — it decides which workspace may be bound, so it is read before one is.
_EXEMPT = {
    ("GET", "/v1/workspaces"),
    ("POST", "/v1/workspaces"),
    ("GET", "/v1/workspaces/guests"),
    ("POST", "/v1/workspaces/guests"),
    ("DELETE", "/v1/workspaces/guests/{grant_id}"),
}


def _api_routes(routes: Any) -> list[APIRoute]:
    """Flatten the app's routes, following lazily-included routers.

    FastAPI defers router inclusion behind a wrapper, so a plain pass over
    ``app.routes`` finds only ``/health`` — which would make every assertion
    below pass while checking nothing.
    """
    found: list[APIRoute] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(_api_routes(route.original_router.routes))
        elif hasattr(route, "routes"):
            found.extend(_api_routes(route.routes))
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
        f"workspace through CurrentWorkspaceId or PathWorkspaceId: {unbound}"
    )


def test_the_exemptions_still_exist() -> None:
    """An exemption for a route that is gone hides the next one worth looking at."""
    # Arrange
    from main import app

    live = {(sorted(r.methods - {"HEAD", "OPTIONS"})[0], r.path) for r in _api_routes(app.routes)}

    # Assert
    assert live >= _EXEMPT, f"exemption names a route that no longer exists: {_EXEMPT - live}"
