"""The only way a diagnostic may reach production data.

A one-off probe against production runs in the worker container, and the worker
connects as the table OWNER: row-level security does not apply to it, no route
guard is in the path, and nothing asks which кабинет is being read. That is
correct for the fleet-wide harvests — they legitimately cross tenants — and it
means an ad-hoc script inherits the same reach by accident. On 2026-09-17 a
performance probe did exactly that: it picked "the кабинет with the most rows",
which was a **paying customer's**, and printed that customer's revenue into a
transcript.

So a diagnostic does not get a session of its own. It gets this one, and it
carries three things it cannot take off:

* ``SET TRANSACTION READ ONLY`` — PostgreSQL refuses every write, DDL included,
  whatever the role is allowed to do. Not a promise about intent: a rule the
  server enforces.
* ``SET LOCAL ROLE`` to the restricted application role, which is
  ``NOBYPASSRLS``. Dropping the owner's privileges is what makes the policies
  apply at all.
* The tenant, bound the way a request binds it. With the policies in force,
  every covered table then answers for :data:`DIAGNOSTIC_WORKSPACE` and nothing
  else — and the monitoring tables, which carry no workspace of their own, are
  reached through ``product_card``, which is covered.

There is no parameter for the workspace. A diagnostic cannot ask for another
one, because asking is the mistake this exists to make impossible.

None of this binds an operator who opens their own connection instead — nothing
in the database can stop the owner role. What it does is make the safe path the
short one, and leave any other path a deliberate act rather than a default.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import AsyncSessionLocal

#: The one кабинет a diagnostic may read: «Демо», the operator's own.
#:
#: A constant rather than an environment variable, so the gate works on a box
#: nobody has configured — a probe that fell back to "no restriction" when the
#: setting was missing would be no gate at all. `DIAGNOSTIC_WORKSPACE_ID`
#: overrides it for another deployment.
DIAGNOSTIC_WORKSPACE = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")

#: PostgreSQL will not take a role name as a bound parameter, so the name is
#: interpolated — and therefore has to be proved to be a bare identifier first.
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

#: The role the API connects as: restricted, and NOBYPASSRLS. The diagnostic
#: drops to it so the policies apply to the probe exactly as they apply to a
#: request.
RESTRICTED_ROLE = "marketplace_app"


class DiagnosticGateError(RuntimeError):
    """The gate could not be established, so no query may run behind it."""


def diagnostic_workspace() -> uuid.UUID:
    """Return the кабинет diagnostics are allowed to read.

    Raises:
        DiagnosticGateError: The override is set to something that is not a
            UUID. Fails closed: an unreadable allowlist is not an empty one.
    """
    override = settings.diagnostic_workspace_id
    if not override:
        return DIAGNOSTIC_WORKSPACE
    try:
        return uuid.UUID(override)
    except ValueError as exc:
        raise DiagnosticGateError("DIAGNOSTIC_WORKSPACE_ID is not a UUID.") from exc


@asynccontextmanager
async def diagnostic_session() -> AsyncIterator[AsyncSession]:
    """Open a read-only session pinned to :func:`diagnostic_workspace`.

    Yields:
        A session that can read one кабинет and write nothing.

    Raises:
        DiagnosticGateError: The restricted role's name is not a plain
            identifier, or the role does not exist on this database. Both mean
            the pinning cannot be established — and a session that merely
            *tried* to pin is the owner's session with extra steps.
    """
    if not _IDENTIFIER.match(RESTRICTED_ROLE):
        raise DiagnosticGateError("The restricted role must be a bare identifier.")
    workspace = diagnostic_workspace()

    async with AsyncSessionLocal() as session:
        # Read-only FIRST: `SET TRANSACTION` is only accepted before the
        # transaction has run anything else.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            await session.execute(text(f"SET LOCAL ROLE {RESTRICTED_ROLE}"))
        except Exception as exc:
            raise DiagnosticGateError(
                f"Could not drop to {RESTRICTED_ROLE}; refusing to read as the owner."
            ) from exc
        await session.execute(
            text("SELECT set_config('app.workspace_id', :value, true)"),
            {"value": str(workspace)},
        )
        yield session


__all__ = [
    "DIAGNOSTIC_WORKSPACE",
    "RESTRICTED_ROLE",
    "DiagnosticGateError",
    "diagnostic_session",
    "diagnostic_workspace",
]
