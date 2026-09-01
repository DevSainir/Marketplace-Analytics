"""Telling the database which tenant a request belongs to (register P2.5).

Application-level scoping is enforced and tested: every tenant-scoped query
takes a `workspace_id`, and `test_export_loaders_are_scoped.py` and friends fail
if one stops. That is a good control with one structural weakness — it is a
promise made by *every* query, so it holds only as long as nobody writes a new
one that forgets. The failure is silent and looks like working code.

Row-level security moves the promise into the database, where a forgotten
`WHERE` returns nothing instead of everything: the "even with a plain SQL query"
property. The policies live in `scripts/sql/row_level_security.sql`; this module
is the half that has to run per request — telling Postgres *which* tenant is
asking.

Why `set_config` and not `SET LOCAL`
------------------------------------
`SET LOCAL app.workspace_id = '...'` cannot take a bound parameter, so using it
would mean interpolating a value into SQL — in the one place whose entire job is
to stop a caller reaching another tenant's rows. `set_config(name, value, true)`
is the function form and takes parameters normally. The `true` is what makes it
**transaction-local**: it unwinds with the request's transaction, so a pooled
connection cannot carry one caller's tenant into the next caller's query.

Why nothing here fails open
---------------------------
The policies read `current_setting('app.workspace_id')` *without* `missing_ok`,
so a query that reaches those tables with no tenant set raises rather than
quietly returning zero rows. That is deliberate and it is the harder of the two
choices to live with: an empty result looks like "this customer has no data" and
gets "fixed" by deleting the scoping, while an error is unmissable. Loud beats
tidy for a control nobody looks at until it has already failed.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings

#: The GUC the policies read. Namespaced under `app.` because PostgreSQL only
#: permits custom settings with a prefix, and `app` says whose it is.
WORKSPACE_SETTING = "app.workspace_id"


async def set_workspace_context(session: AsyncSession, workspace_id: uuid.UUID) -> None:
    """Bind this transaction to one workspace, for row-level security.

    Called from the tenancy choke point (`get_current_workspace_id`) once the
    header has been validated against the caller's organisation — never before.
    Setting it earlier would mean announcing a tenant the caller has not been
    shown to belong to, which is the check the whole route rests on.

    A no-op unless the policies are actually installed. That is not a
    micro-optimisation: with no policy reading it, the statement is a round trip
    per request that buys nothing, and the flag is the one place that records
    whether this deployment's database enforces tenancy or merely trusts the
    application to. See `row_level_security_enabled`.

    Args:
        session: The request's session. Must already be in a transaction, which
            it is: the workspace was just read through it.
        workspace_id: The validated workspace.
    """
    if not settings.row_level_security_enabled:
        return
    await session.execute(
        text(f"SELECT set_config('{WORKSPACE_SETTING}', :value, true)"),
        {"value": str(workspace_id)},
    )


__all__ = ["WORKSPACE_SETTING", "set_workspace_context"]
