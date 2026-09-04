"""The redaction contract for logs and Sentry (register P2.2).

Two sinks retain what this service says about itself, and both are read by more
people, for longer, than the database is. A WB seller token that reaches Loki
has been copied out of the column where it is Fernet-encrypted at rest
(register P1.11) into a store with none of those controls — so the scrubber is
the thing standing between a careless ``%s`` and undoing that.

The cases below are organised around the two ways it can fail, because they
fail in opposite directions and a test suite that only covers one gives false
confidence:

**Too little.** A credential survives. Every value-shape this codebase actually
produces gets a case — a JWT (which is what a WB token is), a bcrypt digest, a
Fernet ciphertext, a DSN password, a proxy URL — and each is asserted both as
a named field and loose inside a sentence, since the second is how it really
happens.

**Too much.** The correlation ids are eaten. That is not hypothetical either:
``trace_id`` is 32 hex characters, the digest pattern looks for 32 hex
characters, and the first run of this scrubber redacted the single field the
whole logging design exists to carry. A redaction that hides nothing and
destroys the evidence is the worse of the two failures, because it looks like
it is working.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import pytest

from src.core import logcontext
from src.core.logging import JsonFormatter
from src.core.observability.scrubbing import REDACTED, scrub_event, scrub_text
from src.core.security import hash_password

#: A structurally valid JWT. WB's own seller tokens are JWTs, so this one
#: pattern covers both our access tokens and every WB credential in the process.
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g"

#: A bcrypt digest, produced by the function this codebase actually hashes
#: with rather than typed out by hand. The first version of this constant was
#: a plausible-looking string of the wrong length, which the pattern correctly
#: refused to match — a test fixture that had drifted from the thing it stood
#: for, in the one place that would have gone unnoticed.
BCRYPT = hash_password("correct-horse-battery-staple")

#: A Fernet token — how every workspace WB token is stored (register P1.11).
FERNET = "gAAAAABmXk9pQ7Zt3vN8Lw2Rk5YxJhFcVbNmQwErTyUiOpAsDfGhJkL"


@pytest.fixture(autouse=True)
def _clean_context() -> Any:
    """Nothing bound before a test, nothing left bound after one."""
    logcontext.reset_context()
    yield
    logcontext.reset_context()


def _render(message: str = "something happened", **extra: Any) -> dict[str, Any]:
    """Format one record through the production formatter and parse it."""
    record = logging.LogRecord("src.test", logging.INFO, "x.py", 1, message, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return json.loads(JsonFormatter().format(record))


# --------------------------------------------------------------------------- #
# Too little: a credential survives.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "secret"),
    [
        ("a WB seller token / our own access token", JWT),
        ("a stored password digest", BCRYPT),
        ("an encrypted WB token at rest", FERNET),
    ],
)
def test_a_credential_is_redacted_even_with_no_field_around_it(name: str, secret: str) -> None:
    """The case that actually happens: interpolated into a sentence.

    Nobody writes ``logger.info("...", extra={"token": token})``. They write
    ``f"WB rejected {token}"``, or let an exception's own message carry it. So
    the value patterns have to work with no field name to go on at all.
    """
    # Act
    payload = _render(f"WB rejected {secret} for this workspace")

    # Assert
    assert secret not in payload["message"], name
    assert REDACTED in payload["message"]
    # The rest of the sentence survives — this is a redactor, not a sanitiser,
    # and a line reduced to "[redacted]" would be no more useful than no line.
    assert "WB rejected" in payload["message"]
    assert "for this workspace" in payload["message"]


@pytest.mark.parametrize(
    "field",
    [
        "password",
        "password_hash",
        "wb_token",
        "refresh_token",
        "authorization",
        "fernet_secret_key",
        "activation_code",
        "verification_code",
        "api_key",
        "set-cookie",
        "token_fingerprint",
    ],
)
def test_a_field_whose_name_promises_a_credential_is_redacted(field: str) -> None:
    """The key net, over the names this codebase actually uses.

    Matched as a substring, so ``wb_token`` and ``refresh_token`` are both
    caught by one entry rather than needing to be enumerated — which is what
    makes a field nobody has invented yet likely to be covered too.
    """
    # Act
    payload = _render("saving", **{field: "correct-horse-battery-staple"})

    # Assert
    assert payload[field] == REDACTED


def test_a_sensitive_key_takes_its_whole_subtree_with_it() -> None:
    """A credentials block disappears in one step, not field by field.

    Redacting only the scalars underneath would leave the structure — and the
    structure of a credentials object is itself a description of what we hold.
    """
    # Act
    scrubbed = scrub_event({"credentials": {"user": "marketplace", "password": "hunter2"}})

    # Assert
    assert scrubbed["credentials"] == REDACTED


def test_a_dsn_keeps_its_host_and_loses_its_password() -> None:
    """Diagnosability and confidentiality both survive, which is the point.

    A connection failure is unreadable without knowing which host refused it,
    and this is the exact string the WB storefront clients' transport errors
    carry when they fail through a credentialed forward proxy.
    """
    # Act
    scrubbed = scrub_text("could not connect to postgresql://marketplace:s3cret@postgres:5432/db")

    # Assert
    assert "s3cret" not in scrubbed
    assert "postgres:5432" in scrubbed, "the host must survive or the error says nothing"
    assert "postgresql://marketplace" in scrubbed


def test_an_exception_message_is_scrubbed_too() -> None:
    """The exception text is added by a processor, so it must be scrubbed after.

    This is the case that pins the ORDER of the processor chain rather than its
    contents: move the scrubber earlier and this line ships a token, while
    every other test here still passes.
    """
    # Arrange
    record = logging.LogRecord("src.test", logging.ERROR, "x.py", 1, "failed", (), None)
    try:
        raise ValueError(f"upstream refused token {JWT}")
    except ValueError as exc:
        record.exc_info = (type(exc), exc, exc.__traceback__)

    # Act
    payload = json.loads(JsonFormatter().format(record))

    # Assert
    assert JWT not in payload["exception"]
    assert REDACTED in payload["exception"]


def test_the_scrubber_never_raises() -> None:
    """A scrubber that throws loses the line it was protecting, and the reason.

    Worse than losing one line: it raises inside whatever error handler was
    logging, so the failure being reported is replaced by a failure in the
    reporting.
    """

    class Hostile:
        def __repr__(self) -> str:
            raise RuntimeError("no repr for you")

    # Act
    scrubbed = scrub_event({"message": "ok", "thing": Hostile()})

    # Assert
    assert isinstance(scrubbed, dict)
    assert scrubbed.get("scrubbing_failed") is True


# --------------------------------------------------------------------------- #
# Too much: the evidence is eaten.
# --------------------------------------------------------------------------- #


def test_the_correlation_ids_survive_redaction() -> None:
    """The regression that made the exemption list exist.

    ``trace_id`` is 32 hex characters and so is a SHA-256 digest, so the first
    version of this scrubber redacted every trace id in the service. Nothing
    looked broken — the lines were all still there, and the one field that made
    them joinable had quietly become the same constant on every one of them.
    """
    # Arrange
    workspace = uuid.UUID("019f657a-a70c-780a-ac98-f010a1916615")
    logcontext.bind_request(
        request_id="abc123def456", method="GET", path="/api/v1/x", client_ip="10.0.0.9"
    )
    logcontext.bind_workspace(workspace)
    logcontext.bind_actor(uuid.UUID("01a05300-0000-7000-8000-00000000aaaa"))

    # Act
    payload = _render("request served")

    # Assert
    assert len(payload["trace_id"]) == 32, "a 32-hex trace id must not look like a digest"
    assert payload["trace_id"] != REDACTED
    assert payload["request_id"] == "abc123def456"
    assert payload["workspace_id"] == str(workspace)
    assert payload["user_id"] == "01a05300-0000-7000-8000-00000000aaaa"


def test_an_error_code_is_not_treated_as_a_secret() -> None:
    """``code`` is deliberately absent from the sensitive-key list.

    ``AppError.code`` appears in nearly every warning this service writes.
    Redacting it would blind the logs to WHY requests fail, in order to hide
    something that is not a secret — while the codes that ARE secret
    (activation, verification, reset) carry their own names and are covered
    above.
    """
    # Act
    payload = _render("Domain error", code="WORKSPACE_NOT_FOUND", status=404)

    # Assert
    assert payload["code"] == "WORKSPACE_NOT_FOUND"
    assert payload["status"] == 404


def test_identity_is_not_confidentiality() -> None:
    """Addresses and names survive, on purpose.

    They are what make a line an answer instead of a fact, and the audit log
    already records an invitee's address deliberately (register P1.3). This
    module hides credentials; redacting identifiers would defeat the reason the
    context is bound at all.
    """
    # Act
    payload = _render("invitation sent", invitee="seller@example.com", workspace_name="Магазин")

    # Assert
    assert payload["invitee"] == "seller@example.com"
    assert payload["workspace_name"] == "Магазин"


def test_ordinary_values_pass_through_untouched() -> None:
    """The baseline, so the cases above are not passing vacuously.

    Types are preserved too: redaction must not read as a schema change to
    whatever parses these lines.
    """
    # Act
    payload = _render("request served", status=200, duration_ms=12.5, retries=0, cached=True)

    # Assert
    assert payload["status"] == 200
    assert payload["duration_ms"] == 12.5
    assert payload["retries"] == 0
    assert payload["cached"] is True
