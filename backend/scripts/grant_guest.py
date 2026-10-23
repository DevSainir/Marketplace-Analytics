"""Open another company's workspace to an account, read-only — from the shell.

The same grant as ``POST /v1/workspaces/guests`` (``src.modules.workspaces.guests``),
for when there is no dev session at hand: the account is promoted to ``head``,
a row lands in ``workspaces.workspace_guests``, and ``WORKSPACE_GUEST_GRANTED``
is written to the audit log with ``--by`` as the actor, in one transaction.

What the grant does NOT give is a way in: the guest still needs an organisation
of their own with a live subscription (``require_member``), or the workspace is
listed and every request answers 403.

Run from the ``backend`` directory::

    python -m scripts.grant_guest --email someone@example.com --workspace "<workspace name>" \\
        --by you@example.com --dry-run

In production, in the worker container (the interpreter with the dependencies)::

    docker exec marketplace-analytics-worker-1 /app/.venv/bin/python \\
        -m scripts.grant_guest --email … --workspace … --by …
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from src.core.database import AsyncSessionLocal
from src.core.exceptions import ConflictError, NotFoundError
from src.modules.organizations.models import AuditEvent
from src.modules.organizations.repos.audit import AuditLogRepository
from src.modules.users.repos import UserRepository
from src.modules.workspaces.guests import grant_guest
from src.modules.workspaces.repos import WorkspaceRepository


async def _run(*, email: str, workspace_name: str, actor: str, dry_run: bool) -> int:
    """Grant ``workspace_name`` to ``email``; return a process exit code."""
    async with AsyncSessionLocal() as session, session.begin():
        users = UserRepository(session)
        dev = await users.get_by_email(actor.strip().lower())
        if dev is None:
            print(f"No account with email {actor} (--by).", file=sys.stderr)
            return 1
        target = await users.get_by_email(email.strip().lower())
        workspace = await WorkspaceRepository(session).get_by_name(workspace_name.strip())
        if target is None or workspace is None:
            print("No such account." if target is None else "No such workspace.", file=sys.stderr)
            return 1
        print(f"{target.email} (role {target.role}) -> {workspace.name} ({workspace.id})")
        if dry_run:
            print("dry run, nothing written")
            return 0
        try:
            grant = await grant_guest(
                session, email=email, workspace_name=workspace_name, granted_by=dev.id
            )
        except (ConflictError, NotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        await AuditLogRepository(session).append(
            event=str(AuditEvent.WORKSPACE_GUEST_GRANTED),
            actor_user_id=dev.id,
            actor_email=dev.email,
            organization_id=None,
            target_type="workspace",
            target_id=str(grant.workspace_id),
            metadata={"grant_id": str(grant.id), "via": "scripts.grant_guest"},
        )
        print(f"granted: {grant.id}")
    return 0


def main() -> None:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True, help="The account to open the workspace to.")
    parser.add_argument("--workspace", required=True, help="The workspace's name, exactly.")
    parser.add_argument("--by", required=True, help="Your email; recorded as the actor.")
    parser.add_argument("--dry-run", action="store_true", help="Show the target, write nothing.")
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            _run(
                email=args.email,
                workspace_name=args.workspace,
                actor=args.by,
                dry_run=args.dry_run,
            )
        )
    )


if __name__ == "__main__":
    main()
