"""The password that lands on a confirmed account is the one bound to its code.

Separate from `test_account_recovery.py` because it is a different subject: that
suite is about the recovery FLOWS — codes expiring, attempts capped, answers not
disclosing whether an address exists. This one is about a single security
property those flows carry, and it is the property an account takeover turned on.
"""

from __future__ import annotations

from tests.support.fakes import FakeUserRepository
from tests.support.recovery import (
    FakeCodeRepo,
    FakeTransport,
)
from tests.support.recovery import (
    build_recovery_service as _service,
)
from tests.support.recovery import (
    code_from as _code_from,
)


async def test_the_password_that_survives_is_the_one_bound_to_the_redeemed_code() -> None:
    """Whoever reads the mailbox chooses the password. Nobody else.

    The attack this closes: an attacker signs up with somebody else's address
    and a password of their own. The victim gets what looks like their own
    confirmation mail — or signs up themselves and is told the address is
    already taken — and confirms. Under the old flow the account went live with
    the ATTACKER's password, because the password was written at registration
    and never replaced.

    Writing it on every attempt instead only reverses who wins. Binding it to
    the code is what removes the window: the confirmation and the choice of
    password are one act.
    """
    # Arrange — the attacker got there first.
    users = FakeUserRepository()
    attacker_digest = "$2b$12$attacker-was-here"
    user = await users.create(email="victim@example.com", hashed_password=attacker_digest)
    user.email_confirmed_at = None
    transport = FakeTransport()
    service = _service(users, FakeCodeRepo(), transport)

    # Act — the victim signs up for their own address, and their password rides
    # on the code that is mailed to them.
    await service.send_confirmation(user=user, pending_password_hash="$2b$12$victims-own")
    await service.confirm_email(email="victim@example.com", code=_code_from(transport))

    # Assert
    assert user.hashed_password == "$2b$12$victims-own"
    assert user.email_confirmed_at is not None


async def test_asking_for_another_code_does_not_drop_the_pending_password() -> None:
    """A resend carries the candidate forward.

    Otherwise «Отправить код ещё раз» would quietly discard the password the
    person typed at signup and leave whatever the account was created with —
    which, in the attack above, is the attacker's.
    """
    # Arrange
    users = FakeUserRepository()
    user = await users.create(email="victim@example.com", hashed_password="$2b$12$attacker")
    user.email_confirmed_at = None
    transport = FakeTransport()
    service = _service(users, FakeCodeRepo(), transport)
    await service.send_confirmation(user=user, pending_password_hash="$2b$12$victims-own")

    # Act — a plain resend knows no password, and must inherit the live one.
    await service.send_confirmation(user=user)
    await service.confirm_email(email="victim@example.com", code=_code_from(transport))

    # Assert
    assert user.hashed_password == "$2b$12$victims-own"


async def test_a_confirmation_without_a_candidate_leaves_the_password_alone() -> None:
    """Codes issued before this existed carry NULL, and must change nothing."""
    # Arrange
    users = FakeUserRepository()
    user = await users.create(email="user@example.com", hashed_password="$2b$12$original")
    user.email_confirmed_at = None
    transport = FakeTransport()
    service = _service(users, FakeCodeRepo(), transport)

    # Act
    await service.send_confirmation(user=user)
    await service.confirm_email(email="user@example.com", code=_code_from(transport))

    # Assert
    assert user.hashed_password == "$2b$12$original"
    assert user.email_confirmed_at is not None
