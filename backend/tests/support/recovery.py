"""In-memory doubles for the verification-code and mail collaborators.

Lifted out of `test_account_recovery.py` when the signup password-binding tests
gave that module a second subject and pushed it past the 500-line ceiling. Two
suites now build the same service, so the scaffolding they share lives here
rather than being copied.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.integrations.email import EmailMessage
from src.modules.users.services.recovery import AccountRecoveryService
from src.modules.users.services.verification import VerificationService
from tests.support.fakes import FakePasswordBreachCheck, FakeUserRepository


class FakeCodeRow:
    """A stored verification code, as the repository hands it back."""

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        purpose: str,
        code_hash: str,
        expires_at: datetime,
        pending_password_hash: str | None = None,
    ):
        """Start live, unconsumed and unguessed."""
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.purpose = purpose
        self.code_hash = code_hash
        self.expires_at = expires_at
        self.consumed_at: datetime | None = None
        self.attempts = 0
        self.pending_password_hash = pending_password_hash


class FakeCodeRepo:
    """In-memory stand-in with the surface the verification service uses."""

    def __init__(self) -> None:
        """Start empty."""
        self.rows: list[FakeCodeRow] = []

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        purpose: str,
        code_hash: str,
        expires_at: datetime,
        pending_password_hash: str | None = None,
    ) -> FakeCodeRow:
        """Store one live code."""
        row = FakeCodeRow(
            user_id=user_id,
            purpose=purpose,
            code_hash=code_hash,
            expires_at=expires_at,
            pending_password_hash=pending_password_hash,
        )
        self.rows.append(row)
        return row

    async def get_live(self, *, user_id: uuid.UUID, purpose: str) -> FakeCodeRow | None:
        """Return the newest redeemable row for this account and purpose."""
        now = datetime.now(UTC)
        live = [
            r
            for r in self.rows
            if r.user_id == user_id
            and r.purpose == purpose
            and r.consumed_at is None
            and r.expires_at > now
        ]
        return live[-1] if live else None

    async def consume_live_codes(self, *, user_id: uuid.UUID, purpose: str) -> int:
        """Kill every live row for this account and purpose."""
        killed = 0
        for row in self.rows:
            if row.user_id == user_id and row.purpose == purpose and row.consumed_at is None:
                row.consumed_at = datetime.now(UTC)
                killed += 1
        return killed

    async def consume(self, row: FakeCodeRow) -> None:
        """Mark one row used."""
        row.consumed_at = datetime.now(UTC)

    async def record_attempt(self, row: FakeCodeRow) -> int:
        """Count a wrong guess."""
        row.attempts += 1
        return row.attempts


class FakeTransport:
    """Captures what would have been mailed."""

    def __init__(self, *, fails: bool = False) -> None:
        """Optionally behave like a relay that is down."""
        self.sent: list[EmailMessage] = []
        self.fails = fails

    async def send(self, message: EmailMessage) -> None:
        """Record the message, or raise like a dead relay."""
        if self.fails:
            raise OSError("relay unreachable")
        self.sent.append(message)


def build_recovery_service(
    users: FakeUserRepository,
    codes: FakeCodeRepo,
    transport: FakeTransport,
    breach_check: FakePasswordBreachCheck | None = None,
) -> AccountRecoveryService:
    """Build the recovery service over in-memory collaborators.

    The breach check is faked even when a test does not care about it: the
    real one is an HTTPS range query, and a unit test that reaches the network
    is slow, offline-fragile, and no longer a unit test.
    """
    return AccountRecoveryService(
        users=users,
        verification=VerificationService(codes=codes),
        transport=transport,
        breach_check=breach_check or FakePasswordBreachCheck(),
    )


def code_from(transport: FakeTransport) -> str:
    """Pull the six digits out of the message that was sent."""
    body = transport.sent[-1].body
    return next(part for part in body.split() if part.isdigit() and len(part) >= 6)


# --------------------------------------------------------------------------- #
# The code itself
# --------------------------------------------------------------------------- #
