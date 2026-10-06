"""Extend an organisation's subscription after a renewal payment.

The one supported way to renew by hand. Find the organisation by the email of
anyone in it (the owner's is what the customer writes from), add the paid days,
and say who did it — the trigger on ``organizations.subscriptions`` records the
change in the audit log with that name on it. A renewal done as a bare
``UPDATE`` in psql is recorded too, but with no actor, which is the reason to
come here instead.

The rule for where the new term starts is
:func:`src.modules.organizations.services.renewal.renewed_expiry`: still open
(before expiry or in grace) continues from the old end, already closed starts
from now.

Run from the ``backend`` directory::

    python -m scripts.extend_subscription --email owner@example.com --days 14 \\
        --by you@example.com --dry-run

On prod, in the worker container (the interpreter with the dependencies)::

    docker exec marketplace-service-worker-1 /app/.venv/bin/python \\
        -m scripts.extend_subscription --email … --days 14 --by …
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

import sqlalchemy as sa

from src.core.database import AsyncSessionLocal
from src.modules.organizations.repos import MembershipRepository, SubscriptionRepository
from src.modules.organizations.services import subscription_state
from src.modules.organizations.services.renewal import extend_subscription, renewed_expiry
from src.modules.users.repos import UserRepository


async def _run(*, email: str, days: int, actor: str, dry_run: bool) -> int:
    """Extend the term of ``email``'s organisation; return a process exit code."""
    async with AsyncSessionLocal() as session, session.begin():
        user = await UserRepository(session).get_by_email(email.strip().lower())
        if user is None:
            print(f"No account with email {email}.", file=sys.stderr)
            return 1
        membership = await MembershipRepository(session).get_for_user(user.id)
        if membership is None:
            print(f"{email} belongs to no organisation.", file=sys.stderr)
            return 1
        subscriptions = SubscriptionRepository(session)
        subscription = await subscriptions.get_for_organization(membership.organization_id)
        if subscription is None:
            print(
                f"Organisation {membership.organization_id} has no subscription.", file=sys.stderr
            )
            return 1

        print(f"Organisation {membership.organization_id}")
        print(
            f"  now:     until {subscription.expires_at:%Y-%m-%d %H:%M} UTC "
            f"({subscription_state(subscription).value}, grace {subscription.grace_days} d)"
        )

        if dry_run:
            new_end = renewed_expiry(
                expires_at=subscription.expires_at,
                grace_days=subscription.grace_days,
                days=days,
                now=datetime.now(UTC),
            )
            print(f"  would be: until {new_end:%Y-%m-%d %H:%M} UTC (dry run, nothing written)")
            return 0

        # Read by the trigger; LOCAL, so it dies with this transaction.
        await session.execute(sa.select(sa.func.set_config("app.audit_actor", actor, True)))
        extension = await extend_subscription(subscriptions, subscription, days=days)
        print(f"  now is:  until {extension.expires_at:%Y-%m-%d %H:%M} UTC (+{days} d)")
    return 0


def main() -> None:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True, help="Email of anyone in the organisation.")
    parser.add_argument("--days", required=True, type=int, help="Paid days to add.")
    parser.add_argument("--by", required=True, help="Your email; recorded as the actor.")
    parser.add_argument("--dry-run", action="store_true", help="Show the result, write nothing.")
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days must be positive")
    sys.exit(
        asyncio.run(_run(email=args.email, days=args.days, actor=args.by, dry_run=args.dry_run))
    )


if __name__ == "__main__":
    main()
