"""Unit tests for the Have I Been Pwned range query.

Driven against a stubbed httpx transport, so nothing here touches the network.

Three properties decide whether this check is worth having. It must find a
password that is in the corpus. It must **never** block a registration by
failing — a third party's outage is not a reason to stop taking customers. And
it must not hand the password, or anything that identifies our users, to
anybody: only five characters of a SHA-1 may leave, which is the whole basis on
which using an external service for this is defensible at all.
"""

from __future__ import annotations

import hashlib

import httpx
import pytest

from src.integrations.pwned import PasswordBreachCheck

#: A password famously present in every breach corpus.
LEAKED = "password123"

#: One that is not, for the negative case.
FRESH = "correct-horse-battery-staple-9271"


def _hash(password: str) -> tuple[str, str]:
    """Return the (prefix, suffix) HIBP would file this password under."""
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    return digest[:5], digest[5:]


def _check_against(handler: object, monkeypatch: pytest.MonkeyPatch) -> PasswordBreachCheck:
    """Build a check whose httpx client is backed by a stub transport."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def _client(**kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _client)
    return PasswordBreachCheck(timeout_seconds=1.0)


@pytest.fixture(autouse=True)
def _enabled(settings_override):
    """Turn the check on; the session default keeps it off everywhere else."""
    with settings_override(password_breach_check_enabled=True):
        yield


async def test_a_listed_password_is_reported_as_breached(monkeypatch) -> None:
    """The whole point: a password already in the corpus is refused."""
    # Arrange
    _, suffix = _hash(LEAKED)
    body = f"0000000000000000000000000000000000A:3\n{suffix}:24230577\n"
    check = _check_against(lambda request: httpx.Response(200, text=body), monkeypatch)

    # Act / Assert
    assert await check.is_breached(LEAKED) is True


async def test_an_unlisted_password_is_allowed(monkeypatch) -> None:
    """A prefix bucket always returns hundreds of rows; ours must not be among them."""
    # Arrange
    body = "0000000000000000000000000000000000A:3\n0000000000000000000000000000000000B:9\n"
    check = _check_against(lambda request: httpx.Response(200, text=body), monkeypatch)

    # Act / Assert
    assert await check.is_breached(FRESH) is False


async def test_only_five_characters_of_the_hash_leave_the_process(monkeypatch) -> None:
    """k-anonymity is the entire justification for calling a third party here."""
    # Arrange
    prefix, suffix = _hash(LEAKED)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=f"{suffix}:1\n")

    check = _check_against(handler, monkeypatch)

    # Act
    await check.is_breached(LEAKED)

    # Assert
    sent = str(seen[0].url)
    assert sent.endswith(f"/range/{prefix}")
    assert suffix not in sent, "the identifying 35 characters must never be sent"
    assert LEAKED not in sent
    assert seen[0].headers["Add-Padding"] == "true", (
        "without padding, the response length narrows down the prefix"
    )


async def test_padding_rows_are_not_treated_as_hits(monkeypatch) -> None:
    """Add-Padding injects zero-count rows; counting one would refuse a good password."""
    # Arrange
    _, suffix = _hash(FRESH)
    check = _check_against(
        lambda request: httpx.Response(200, text=f"{suffix}:0\n"),
        monkeypatch,
    )

    # Act / Assert
    assert await check.is_breached(FRESH) is False


@pytest.mark.parametrize(
    ("response", "case"),
    [
        (httpx.Response(500, text="upstream is unwell"), "server error"),
        (httpx.Response(429, text="slow down"), "rate limited"),
        (httpx.Response(200, text="not a range response at all"), "malformed body"),
    ],
)
async def test_a_failing_service_never_blocks_a_registration(
    response: httpx.Response, case: str, monkeypatch
) -> None:
    """Somebody else's outage must not become a closed signup form."""
    # Arrange
    check = _check_against(lambda request: response, monkeypatch)

    # Act / Assert
    assert await check.is_breached(LEAKED) is False


async def test_a_timeout_never_blocks_a_registration(monkeypatch) -> None:
    """The most likely failure, and the one with the worst UX if it raised."""

    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    check = _check_against(handler, monkeypatch)

    # Act / Assert
    assert await check.is_breached(LEAKED) is False


async def test_the_check_is_a_no_op_when_switched_off(monkeypatch, settings_override) -> None:
    """Off means "allow", never "error" — that is what keeps the tiers hermetic."""

    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the disabled check must not make a request")

    check = _check_against(handler, monkeypatch)

    # Act / Assert
    with settings_override(password_breach_check_enabled=False):
        assert await check.is_breached(LEAKED) is False
