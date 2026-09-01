"""Outbound email — the transport and the messages this service sends.

Kept in ``integrations`` rather than in the users module because it is a third
party we talk to, the same as WildBerries: something outside this process, with
its own failure modes and its own credentials.
"""

from src.integrations.email.messages import (
    confirmation_message,
    password_reset_message,
)
from src.integrations.email.transport import (
    EmailMessage,
    EmailTransport,
    LoggingTransport,
    SmtpTransport,
    get_email_transport,
)

__all__ = [
    "EmailMessage",
    "EmailTransport",
    "LoggingTransport",
    "SmtpTransport",
    "confirmation_message",
    "get_email_transport",
    "password_reset_message",
]
