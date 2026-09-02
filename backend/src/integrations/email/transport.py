"""Sending one message, or convincingly not sending it.

Two transports behind one protocol, and the second is not a testing
convenience — it is what makes the whole feature safe to have in the tree
before a relay exists.

:class:`SmtpTransport` sends. :class:`LoggingTransport` renders the message and
writes it to the application log instead, which is what runs in local
development, in CI and in every test tier. That means the confirmation flow can
be exercised end to end by a developer reading their own console, no test can
mail a real address by accident, and the code path under test is the real one
rather than a mock of it.

Which transport a process gets is decided by ``EMAIL_ENABLED`` alone, in
:func:`get_email_transport`. There is no third state: a deployment that demands
a mail-dependent flow without enabling the transport does not boot (see
``config/assembly.py``), so "enabled but broken" is not a configuration this
service can be left in.

**Failure policy: sending raises.** That is the opposite of the fail-open
choices elsewhere in this codebase, and deliberately so. A rate limiter that
fails open loses a dampener; a confirmation mail that fails silently leaves an
account nobody can finish creating and a user staring at a screen that says it
worked. The caller decides what to tell the person — see the routers, which
turn it into a 502 rather than a lie.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from typing import Protocol

import aiosmtplib

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    """One outbound message, already rendered.

    Attributes:
        to: The single recipient. No bcc, no lists: everything this service
            sends is addressed to one person about their own account, and a
            transport that cannot fan out cannot fan out by mistake.
        subject: Subject line.
        body: Plain-text body, and always the authoritative one. Every client
            can render it, it survives an HTML part being stripped, and it is
            what the logging transport shows a developer.
        html: Optional HTML alternative, sent alongside ``body`` rather than
            instead of it. This started as plain-text-only on the argument that
            an HTML mail is a rendering surface with nothing worth rendering;
            what changed is that a bare six-digit code from an unfamiliar
            sender reads as spam, and a message the recipient distrusts is one
            they do not act on. The HTML here is a logo, a heading and the
            code — no links, no images, no remote fetches, so the surface it
            adds is a colour and a font.
    """

    to: str
    subject: str
    body: str
    html: str | None = None


class EmailTransport(Protocol):
    """What the services need from a mail path."""

    async def send(self, message: EmailMessage) -> None:
        """Deliver one message, or raise."""
        ...


class LoggingTransport:
    """Writes the message to the log instead of sending it.

    The default everywhere until a relay is configured. It logs the subject and
    body **in full**, including any code they carry, and that is intentional: on
    a box with no mail transport the log is the only place the developer running
    the flow can read the code. It is also why this transport must never be what
    a production deployment gets — which is enforced in `assembly.py` rather
    than trusted here.
    """

    async def send(self, message: EmailMessage) -> None:
        """Record the message that would have been sent."""
        logger.info(
            "EMAIL NOT SENT (no transport configured) to=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.body,
        )


class SmtpTransport:
    """Sends over SMTP, with STARTTLS and a bounded wait.

    Args:
        host: Relay hostname.
        port: Relay port (587 for the usual STARTTLS submission service).
        username: SMTP user, or empty for an unauthenticated relay.
        password: SMTP password.
        use_tls: Whether to STARTTLS. Only ever false for a relay on a trusted
            local network — plaintext SMTP over the internet hands every code
            it carries to anyone on the path.
        timeout: Whole-operation budget in seconds. This runs inside a request,
            so a hung relay must not become a hung form.
        sender: The ``From:`` address.
        sender_name: The display name shown beside it.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool,
        timeout: float,
        sender: str,
        sender_name: str,
    ) -> None:
        """Store the relay configuration."""
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._timeout = timeout
        self._sender = sender
        self._sender_name = sender_name

    async def send(self, message: EmailMessage) -> None:
        """Deliver one message.

        Args:
            message: The rendered message.

        Raises:
            aiosmtplib.SMTPException: On any delivery failure. Not swallowed —
                see the module docstring.
        """
        mime = MimeMessage()
        mime["From"] = f"{self._sender_name} <{self._sender}>"
        mime["To"] = message.to
        mime["Subject"] = message.subject
        # Plain text first, HTML second: `add_alternative` orders the parts of
        # a multipart/alternative, and a client picks the LAST one it can
        # render. Reversing these two lines silently makes the text part the
        # one everybody sees.
        mime.set_content(message.body)
        if message.html is not None:
            mime.add_alternative(message.html, subtype="html")

        await aiosmtplib.send(
            mime,
            hostname=self._host,
            port=self._port,
            username=self._username or None,
            password=self._password or None,
            start_tls=self._use_tls,
            timeout=self._timeout,
        )
        # The address is logged, the body never is: it carries the code, and an
        # application log is not a place to keep a live credential.
        logger.info("Sent %r to %s.", message.subject, message.to)


def get_email_transport() -> EmailTransport:
    """Return the transport this process should use.

    Decided by ``EMAIL_ENABLED`` and nothing else. A deployment cannot be in the
    "enabled but unconfigured" state — `Settings._email_configuration_problems`
    refuses to boot it.

    Returns:
        An SMTP transport when mail is enabled, otherwise the logging one.
    """
    if not settings.email_enabled:
        return LoggingTransport()
    return SmtpTransport(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        timeout=settings.smtp_timeout_seconds,
        sender=settings.email_from,
        sender_name=settings.email_from_name,
    )


__all__ = [
    "EmailMessage",
    "EmailTransport",
    "LoggingTransport",
    "SmtpTransport",
    "get_email_transport",
]
