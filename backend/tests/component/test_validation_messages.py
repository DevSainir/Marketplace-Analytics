"""What a 422 says to the person who sent the request.

The SPA shows ``msg`` verbatim, so the handler in ``main.py`` writes it: a
sentence of ours per pydantic error type, and a validator's own complaint only
when the validator wrote it for a person — by raising ``UserInputError``. Any
other ``ValueError`` text is replaced, because a third-party validator's
message can quote the submitted value back, and keeping the value out of the
response is the reason the handler exists.

Component tier because the handler lives in ``main.py``, and importing it
builds the application.
"""

from __future__ import annotations

from main import _validation_message
from src.core.exceptions import UserInputError


def test_a_validators_own_message_reaches_the_person() -> None:
    """A ``UserInputError`` is written for the screen and is passed through."""
    error = {
        "type": "value_error",
        "loc": ("body", "password"),
        "msg": "Value error, The password needs an uppercase letter.",
        "ctx": {"error": UserInputError("The password needs an uppercase letter.")},
    }

    message = _validation_message(error)

    assert message == "The password needs an uppercase letter."


def test_any_other_value_error_is_replaced() -> None:
    """A plain ``ValueError`` may echo the input, so its text never leaves."""
    error = {
        "type": "value_error",
        "loc": ("body", "name"),
        "msg": "Value error, 'hunter2' is not allowed here",
        "ctx": {"error": ValueError("'hunter2' is not allowed here")},
    }

    message = _validation_message(error)

    assert message == "Invalid value."


def test_an_address_field_says_what_is_wrong_with_it() -> None:
    """The commonest mistype gets a sentence of its own, not "Invalid value."."""
    error = {
        "type": "value_error",
        "loc": ("body", "email"),
        "msg": "value is not a valid email address: The domain name x.invalid does not exist",
        "ctx": {"reason": "The domain name x.invalid does not exist"},
    }

    message = _validation_message(error)

    assert message == "Invalid email address."


def test_a_limit_from_the_schema_is_named() -> None:
    """``ctx`` limits are our own constants and are worth saying."""
    error = {
        "type": "string_too_short",
        "loc": ("body", "password"),
        "msg": "String should have at least 8 characters",
        "ctx": {"min_length": 8},
    }

    message = _validation_message(error)

    assert message == "Too short — at least 8 characters."
