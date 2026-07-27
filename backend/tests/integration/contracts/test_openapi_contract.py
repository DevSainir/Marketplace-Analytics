"""Schema-driven contract tests against the generated ``openapi.json``.

**Scope note (read before adding to this file).** Contract testing normally
guards *module-to-module* calls. This monolith has none yet: `contract.py` is
imported in-process, so a breaking change is caught by the type checker, not by
a schema. The one contract that genuinely crosses a process boundary is the one
between **this API and the Vue SPA**, which generates its client types from this
document (``npm run types:api``). That is what these tests guard.

When a module does start calling another over HTTP (or a queue), add its
consumer-driven contract here and mirror the split in
``docs/rules/current_tests.md``.

The failure these tests exist to prevent: a renamed field or a widened
nullability ships, the SPA's generated types are not regenerated, and the UI
silently renders ``undefined`` in a money column.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.openapi.utils import get_openapi

#: Every response body the SPA reads. A field disappearing from one of these is
#: a breaking change for the frontend even when every backend test still passes.
CONSUMED_SCHEMAS: dict[str, set[str]] = {
    "TokenPairResponse": {"access_token", "token_type", "expires_at"},
    "UserRead": {"id", "email", "is_active", "role", "created_at"},
    "WorkspaceRead": {"id", "name", "is_primary", "created_at"},
    "WorkspaceListResponse": {"items"},
    "WorkspaceTokensStatus": {"workspace_id", "is_primary", "configured"},
    "SkuSummaryListResponse": {"window", "count", "total", "limit", "offset", "items"},
    "SkuLookupResponse": {"query", "count", "items"},
    "PinnedSkusResponse": {"items"},
    "WeeksResponse": {"weeks"},
}

#: The subset of consumed fields whose *optionality* also matters. A collection
#: declared with ``default_factory=list`` is always sent by the server but is
#: reported as optional in the document (Pydantic emits no ``default`` for a
#: factory), so the generated client types it as ``T[] | undefined``. That is
#: harmless for a list the UI iterates; it would be a silent blank cell for a
#: scalar the UI renders, so scalars are listed here and collections are not.
REQUIRED_FIELDS: dict[str, set[str]] = {
    "TokenPairResponse": {"access_token", "expires_at"},
    "UserRead": {"id", "email", "is_active", "role"},
    "WorkspaceRead": {"id", "name", "is_primary"},
    "WorkspaceTokensStatus": {"workspace_id", "is_primary", "configured"},
    "SkuSummaryListResponse": {"window", "count", "total", "limit", "offset"},
    "SkuLookupResponse": {"query", "count"},
}

#: Routes the SPA calls by literal path. A rename here is an instant 404 in the
#: browser, with no compile-time warning anywhere.
CONSUMED_ROUTES: list[tuple[str, str]] = [
    ("post", "/api/v1/auth/login"),
    ("post", "/api/v1/auth/refresh"),
    ("post", "/api/v1/auth/logout"),
    ("get", "/api/v1/auth/me"),
    ("get", "/api/v1/workspaces"),
    ("get", "/api/v1/monitoring/summary"),
    ("get", "/api/v1/monitoring/skus/lookup"),
    ("get", "/api/v1/monitoring/skus/{nm_id}"),
    ("get", "/api/v1/monitoring/pins"),
    ("get", "/api/v1/finreports/weeks"),
]


@pytest.fixture(scope="module")
def openapi() -> dict[str, Any]:
    """Generate the OpenAPI document exactly as ``/openapi.json`` serves it."""
    from main import app

    return get_openapi(
        title=app.title, version=app.version, routes=app.routes, description=app.description
    )


def test_the_document_generates_at_all(openapi: dict[str, Any]) -> None:
    """Schema generation must not raise.

    An un-serializable response model breaks ``/docs`` and the frontend's type
    generation together, and the failure only appears when someone opens them.
    """
    assert openapi["openapi"].startswith("3.")
    assert openapi["paths"]


@pytest.mark.parametrize(("method", "path"), CONSUMED_ROUTES)
def test_route_consumed_by_the_spa_still_exists(
    openapi: dict[str, Any], method: str, path: str
) -> None:
    """Each path the SPA calls is still published under the same verb."""
    assert path in openapi["paths"], f"{path} disappeared from the API surface"
    assert method in openapi["paths"][path]


@pytest.mark.parametrize(("schema_name", "fields"), sorted(CONSUMED_SCHEMAS.items()))
def test_response_schema_keeps_the_fields_the_spa_reads(
    openapi: dict[str, Any], schema_name: str, fields: set[str]
) -> None:
    """No consumed field may be renamed or dropped without updating this list.

    Editing this test is the point: it forces the frontend change into the same
    commit as the backend one.
    """
    schemas = openapi["components"]["schemas"]
    assert schema_name in schemas, f"{schema_name} is no longer part of the public API"

    published = set(schemas[schema_name].get("properties", {}))

    assert fields <= published, f"{schema_name} lost {sorted(fields - published)}"


@pytest.mark.parametrize(("schema_name", "fields"), sorted(REQUIRED_FIELDS.items()))
def test_scalar_fields_the_spa_renders_stay_required(
    openapi: dict[str, Any], schema_name: str, fields: set[str]
) -> None:
    """A scalar going optional is a silent break for a generated client.

    The SPA's types would turn it into ``T | undefined`` and every read site
    would need a guard nobody adds — the value just renders blank, which in a
    money column is worse than an error.
    """
    schema = openapi["components"]["schemas"][schema_name]
    required = set(schema.get("required", []))
    # A field carrying an explicit default is legitimately optional to send.
    defaulted = {name for name, spec in schema.get("properties", {}).items() if "default" in spec}

    missing = fields - required - defaulted

    assert missing == set(), f"{schema_name} made {sorted(missing)} optional"


def test_no_token_value_is_ever_part_of_a_response_schema(openapi: dict[str, Any]) -> None:
    """WB credentials must not appear in any published response shape.

    ``WorkspaceTokenBundle`` carries decrypted WB tokens for the harvest and is
    deliberately internal. If it ever became reachable from a route, the
    document would advertise plaintext seller credentials.
    """
    assert "WorkspaceTokenBundle" not in openapi["components"]["schemas"]


def test_every_protected_route_declares_a_security_scheme(openapi: dict[str, Any]) -> None:
    """Auth is declared in the document, not just enforced in code.

    Without it the generated client omits the ``Authorization`` header and every
    call 401s at runtime.
    """
    # Deliberately unauthenticated: the three credential-exchange routes, plus
    # /logout — it authenticates with the refresh *cookie* alone, so a client
    # whose access token has already expired can still end its session instead
    # of leaving a live refresh family behind.
    public = {
        "/health",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
    }
    unprotected: list[str] = []

    for path, operations in openapi["paths"].items():
        if path in public:
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "delete", "patch"}:
                continue
            if not operation.get("security"):
                unprotected.append(f"{method.upper()} {path}")

    assert unprotected == [], f"Routes missing a declared security scheme: {unprotected}"


def test_every_operation_documents_an_error_response(openapi: dict[str, Any]) -> None:
    """Each route declares more than the happy path.

    ``architecture_rules.md`` requires explicit status codes; a document that
    lists only 200 tells a client nothing about how failures look.
    """
    happy_path_only: list[str] = []

    for path, operations in openapi["paths"].items():
        if path == "/health":
            continue
        for method, operation in operations.items():
            if method not in {"get", "post", "put", "delete", "patch"}:
                continue
            codes = {code for code in operation.get("responses", {}) if code.startswith(("4", "5"))}
            if not codes:
                happy_path_only.append(f"{method.upper()} {path}")

    assert happy_path_only == [], f"Routes documenting no failure mode: {happy_path_only}"


def test_the_logout_route_is_documented_as_no_content(openapi: dict[str, Any]) -> None:
    """204 is part of the contract: the SPA must not try to parse a body.

    Reading JSON from a 204 throws in the browser, which the axios layer would
    surface as a failed logout even though the session really ended.
    """
    responses = openapi["paths"]["/api/v1/auth/logout"]["post"]["responses"]

    assert "204" in responses
