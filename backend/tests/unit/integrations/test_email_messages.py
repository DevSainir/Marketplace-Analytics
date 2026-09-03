"""What the two recovery mails must contain, and must not.

The rendering is cosmetic; three of its properties are not. A code that
reaches only the HTML part is invisible to a text client, a remote asset turns
opening the mail into a report back to whoever hosts it, and a link is the
thing a phishing copy needs. Each is pinned here because each would survive a
redesign unnoticed.
"""

from __future__ import annotations

import pytest

from src.integrations.email import confirmation_message, password_reset_message

_BUILDERS = [confirmation_message, password_reset_message]


@pytest.mark.parametrize("build", _BUILDERS)
def test_the_code_is_in_the_text_part_not_only_the_html(build) -> None:
    # Arrange / Act
    message = build(to="seller@example.com", code="864346", ttl_minutes=20)

    # Assert — the text body is what the logging transport shows a developer
    # and what a text-only client renders.
    assert "864346" in message.body


@pytest.mark.parametrize("build", _BUILDERS)
def test_the_html_carries_the_code_as_one_unbroken_token(build) -> None:
    """The digits are spaced by CSS, never by real spaces.

    This assertion is the reverse of the one it replaces, which required
    ``8 6 4 3 4 6`` in the markup. Literal spaces did read well and copied
    badly: selecting the code — the thing every recipient does with it — put
    ``8 6 4 3 4 6`` on the clipboard, which no code field accepts. Spacing is
    now `letter-spacing`, so it still reads apart and pastes clean.
    """
    # Arrange / Act
    message = build(to="seller@example.com", code="864346", ttl_minutes=20)

    # Assert
    assert message.html is not None
    assert "864346" in message.html
    assert "8 6 4 3 4 6" not in message.html
    # One tap selects the whole code and nothing around it — the closest a
    # mail client gets to a copy button, since none of them run JavaScript.
    assert "user-select:all" in message.html


@pytest.mark.parametrize("build", _BUILDERS)
def test_the_code_is_still_visually_spaced(build) -> None:
    """Losing the real spaces must not lose the readability they bought."""
    # Arrange / Act
    message = build(to="seller@example.com", code="864346", ttl_minutes=20)

    # Assert
    assert message.html is not None
    assert "letter-spacing" in message.html


@pytest.mark.parametrize("build", _BUILDERS)
def test_neither_part_fetches_anything_or_offers_a_link(build) -> None:
    # Arrange / Act
    message = build(to="seller@example.com", code="864346", ttl_minutes=20)

    # Assert — no <img>, no <a>, and no scheme anywhere. A remote image is a
    # read receipt for its host; a link is what a phishing copy imitates.
    assert message.html is not None
    for fragment in ("<img", "<a ", "http://", "https://"):
        assert fragment not in message.html
        assert fragment not in message.body


@pytest.mark.parametrize("build", _BUILDERS)
def test_the_stated_lifetime_follows_the_argument(build) -> None:
    # Arrange / Act — 20 is the configured default, so a wrong-but-plausible
    # hardcoded string would pass at 20 and only fail here.
    message = build(to="seller@example.com", code="864346", ttl_minutes=7)

    # Assert
    assert message.html is not None
    assert "7 minutes" in message.html
    assert "7 minutes" in message.body


@pytest.mark.parametrize("build", _BUILDERS)
def test_every_message_says_what_to_do_if_it_was_not_you(build) -> None:
    # Arrange / Act
    message = build(to="seller@example.com", code="864346", ttl_minutes=20)

    # Assert — the earliest warning a person gets that somebody is trying
    # their address. The reference design this follows omits it; we do not.
    assert message.html is not None
    assert "did not" in message.body
    assert "did not" in message.html


def test_the_two_subjects_are_the_ones_the_product_promises() -> None:
    # Arrange / Act
    confirmation = confirmation_message(to="a@example.com", code="111111", ttl_minutes=20)
    recovery = password_reset_message(to="a@example.com", code="222222", ttl_minutes=20)

    # Assert
    assert confirmation.subject == "Signup confirmation code"
    assert recovery.subject == "Recovery code"
