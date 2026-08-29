"""The app must not publish its own route inventory outside local development.

Register item P0.2. ``/docs``, ``/redoc`` and ``/openapi.json`` were mounted
unconditionally. They were never actually reachable in production — nginx
proxies only ``/api/`` and the three live at the app root, so the public site
answers them with the SPA shell — but nothing about that was deliberate. A
``--root-path /api``, a new nginx location, or the API port being published
would each have turned a routing accident into full disclosure.

So the switch is here, in the app, where the exposure would be; the routing is
not treated as the control.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from main import documentation_urls
from src.core.config import settings


def test_a_deployed_environment_withholds_the_schema_too() -> None:
    """Disabling the docs disables ``/openapi.json`` with them.

    The half-fix — hiding the two viewers, leaving the schema — withholds
    nothing at all, since the schema is the inventory and the viewers merely
    render it. Pinning the three together is the point of the test.
    """
    withheld = documentation_urls(enabled=False)

    assert withheld == (None, None, None)


def test_local_development_still_gets_all_three() -> None:
    """The dev affordance must not quietly disappear everywhere instead."""
    offered = documentation_urls(enabled=True)

    assert offered == ("/docs", "/redoc", "/openapi.json")


def test_the_running_app_follows_the_configured_switch(app: FastAPI) -> None:
    """The real app is wired from the setting, not from a literal.

    Without this the helper could be correct while ``main`` kept mounting the
    defaults — the bug would survive its own fix.
    """
    expected = documentation_urls(enabled=settings.api_docs_enabled)

    assert (app.docs_url, app.redoc_url, app.openapi_url) == expected


async def test_the_schema_is_not_served_when_it_is_withheld() -> None:
    """A withheld schema 404s: the route is unmounted, not merely unlinked.

    ``None`` must remove the endpoint. Were it only hidden from the docs page,
    a direct request would still hand over the whole surface.
    """
    withheld = documentation_urls(enabled=False)
    blank = FastAPI(
        docs_url=withheld.docs_url,
        redoc_url=withheld.redoc_url,
        openapi_url=withheld.openapi_url,
    )

    transport = httpx.ASGITransport(app=blank)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        answers = [
            (await client.get(path)).status_code for path in ("/docs", "/redoc", "/openapi.json")
        ]

    assert answers == [404, 404, 404]
