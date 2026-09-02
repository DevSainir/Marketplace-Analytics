"""How a message becomes MIME, and which part a client ends up showing.

`multipart/alternative` is ordered least-preferred first: a client renders the
LAST part it understands. Swapping the two `set_content`/`add_alternative`
lines is therefore silent — the mail still sends, still has both parts, and
every recipient sees the plain text. Only an assertion on the order catches it.
"""

from __future__ import annotations

import aiosmtplib
import pytest

from src.integrations.email import EmailMessage, LoggingTransport, SmtpTransport


def _transport() -> SmtpTransport:
    return SmtpTransport(
        host="smtp.example.com",
        port=2587,
        username="user",
        password="secret",
        use_tls=True,
        timeout=10.0,
        sender="noreply@example.com",
        sender_name="Marketplace Analytics",
    )


@pytest.fixture
def captured(monkeypatch) -> list:
    """Capture the MIME object instead of sending it."""
    sent: list = []

    async def _fake_send(mime, **kwargs):
        sent.append(mime)

    monkeypatch.setattr(aiosmtplib, "send", _fake_send)
    return sent


async def test_an_html_message_carries_both_parts_with_html_last(captured) -> None:
    # Arrange
    message = EmailMessage(
        to="seller@example.com", subject="Recovery code", body="text form", html="<p>rich</p>"
    )

    # Act
    await _transport().send(message)

    # Assert
    mime = captured[0]
    assert mime.is_multipart()
    subtypes = [part.get_content_subtype() for part in mime.iter_parts()]
    assert subtypes == ["plain", "html"], "html must be last or clients show the text part"


async def test_a_text_only_message_stays_a_single_part(captured) -> None:
    # Arrange — the logging-transport shape, and anything sent before the
    # HTML alternative existed.
    message = EmailMessage(to="seller@example.com", subject="Plain", body="text form")

    # Act
    await _transport().send(message)

    # Assert
    assert not captured[0].is_multipart()


async def test_the_sender_display_name_is_the_one_configured(captured) -> None:
    # Arrange
    message = EmailMessage(to="seller@example.com", subject="Recovery code", body="text")

    # Act
    await _transport().send(message)

    # Assert
    assert captured[0]["From"] == "Marketplace Analytics <noreply@example.com>"


async def test_the_logging_transport_never_reaches_the_network(captured) -> None:
    # Arrange
    message = EmailMessage(to="seller@example.com", subject="Recovery code", body="text")

    # Act
    await LoggingTransport().send(message)

    # Assert — this is the property that makes the feature safe to have in the
    # tree with no relay: nothing left the process.
    assert captured == []
