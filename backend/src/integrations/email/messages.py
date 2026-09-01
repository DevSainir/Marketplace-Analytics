"""The two messages this service sends, and their wording.

Kept apart from the transport because they are a different kind of thing: the
transport is plumbing, this is what a customer reads. Russian, like every other
string a customer sees.

Both say the same three things, in the same order, because both are sent to
someone who may not have asked for them: what the code is for, how long it
lives, and what to do if it was not you. The last line is the one that matters —
an unexpected reset mail is the earliest warning a person gets that somebody is
trying their address, and a mail that omits it wastes that.

Neither message contains a link. A code the person retypes cannot be clicked
from a phishing copy of this mail, and there is no URL for a mail client to
rewrite or a scanner to visit — which is how one-click reset links get consumed
before the human sees them.
"""

from __future__ import annotations

from src.integrations.email.transport import EmailMessage


def confirmation_message(*, to: str, code: str, ttl_minutes: int) -> EmailMessage:
    """Build the address-confirmation message.

    Args:
        to: Recipient address.
        code: The plaintext code. Exists here and in the mail, nowhere else.
        ttl_minutes: How long the code stays valid.

    Returns:
        The rendered message.
    """
    return EmailMessage(
        to=to,
        subject="Подтверждение адреса — Аналитика маркетплейса",
        body=(
            "Здравствуйте!\n\n"
            "Ваш код для подтверждения адреса:\n\n"
            f"    {code}\n\n"
            f"Код действует {ttl_minutes} минут и работает один раз.\n\n"
            "Если вы не регистрировались в сервисе, просто проигнорируйте это "
            "письмо — без кода учётная запись не будет подтверждена.\n"
        ),
    )


def password_reset_message(*, to: str, code: str, ttl_minutes: int) -> EmailMessage:
    """Build the password-reset message.

    Args:
        to: Recipient address.
        code: The plaintext code.
        ttl_minutes: How long the code stays valid.

    Returns:
        The rendered message.
    """
    return EmailMessage(
        to=to,
        subject="Восстановление пароля — Аналитика маркетплейса",
        body=(
            "Здравствуйте!\n\n"
            "Ваш код для смены пароля:\n\n"
            f"    {code}\n\n"
            f"Код действует {ttl_minutes} минут и работает один раз.\n"
            "После смены пароля все активные сессии будут завершены — на всех "
            "устройствах придётся войти заново.\n\n"
            "Если вы не запрашивали смену пароля, никаких действий не требуется: "
            "без кода пароль изменить нельзя. Но это значит, что кто-то ввёл ваш "
            "адрес в форму восстановления — если такое повторяется, сообщите нам.\n"
        ),
    )


__all__ = ["confirmation_message", "password_reset_message"]
