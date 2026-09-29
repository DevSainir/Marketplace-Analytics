"""Every WB client that talks to the seller API must hold a rate gate.

``BaseWBClient`` defaults ``rate_gate`` to :class:`NullRateGate`, which makes an
unpaced client indistinguishable from a paced one at the call site: it simply
never waits. Six of them were exempt that way until 2026-09-15 — content,
and three of those run on every single harvest.

That is the shape of the failure this file exists to stop: not one greedy
endpoint, but a drift of small ones. WB meters per endpoint, so each is
individually harmless and collectively a 429 on a surface something else was
counting on — and the 429 does not arrive politely (the analytics surface
answers 500, or holds the socket until the read timeout).

The test asserts the property rather than a list, so a client added tomorrow is
covered without anyone remembering this file exists.
"""

from __future__ import annotations

import inspect
import pkgutil
from importlib import import_module
from pathlib import Path

import pytest

from src.core.config import Settings
from src.integrations.wildberries import clients as clients_pkg
from src.integrations.wildberries.clients.base import BaseWBClient
from src.integrations.wildberries.rate_limit import NullRateGate

#: Clients whose transport is NOT the seller API, with the reason. The
#: storefront card endpoint is unauthenticated (``card.wb.ru``), so there is no
#: token to key a bucket by and no seller budget to protect; it is bounded
#: instead by its own concurrency semaphore and a tight retry cap, and it does
#: not subclass :class:`BaseWBClient` at all — which is why it cannot reach this
#: test in the first place. Listed so the absence is a decision on the record.
_NOT_SELLER_API: dict[str, str] = {
    "WBCardClient": "public storefront via curl; no token, own semaphore",
}

#: Clients that take their gate from the caller, because the right bucket depends
#: on which host the caller points them at — and the test that checks those
#: callers instead. Until 2026-09-29 such a client was simply skipped below, and
#: the skip hid a real gap: the guide's tariff captures on the `common` host,
#: which the daily tariff harvest also uses, ran with no gate at all.
_GATE_FROM_CALLER: dict[str, str] = {
    "WBReferenceClient": "tests/unit/guide/test_capture_pacing.py",
}


def _client_classes() -> list[type[BaseWBClient]]:
    """Every concrete ``BaseWBClient`` subclass in the clients package."""
    found: dict[str, type[BaseWBClient]] = {}
    for module in pkgutil.iter_modules(clients_pkg.__path__):
        mod = import_module(f"{clients_pkg.__name__}.{module.name}")
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if issubclass(obj, BaseWBClient) and obj is not BaseWBClient:
                found[obj.__name__] = obj
    return sorted(found.values(), key=lambda c: c.__name__)


def test_the_scan_actually_finds_the_clients() -> None:
    """A guard that silently matches nothing passes forever."""
    names = {c.__name__ for c in _client_classes()}

    assert "WBAdvertisingClient" in names
    assert "WBStatisticsClient" in names
    assert len(names) >= 8


@pytest.mark.parametrize("client_cls", _client_classes(), ids=lambda c: c.__name__)
def test_a_wb_client_takes_a_rate_gate(client_cls: type[BaseWBClient]) -> None:
    """The constructor must pass one — accepting it as an argument is not enough.

    ``WBReferenceClient`` takes its gate from the caller because the right
    bucket depends on which surface the reference data is being read from; the
    assertion below is satisfied by either shape, since what matters is that the
    gate is reachable at all rather than where it was built.
    """
    source = inspect.getsource(client_cls)

    assert "rate_gate=" in source, (
        f"{client_cls.__name__} never passes rate_gate to BaseWBClient, so it "
        "inherits NullRateGate and is paced by nothing. Add a gate from "
        "src.integrations.wildberries.rate_limit."
    )


def test_every_caller_gated_client_names_a_test_that_exists() -> None:
    """An exemption pointing at a file nobody wrote is the old skip with extra steps."""
    root = Path(__file__).resolve().parents[3]

    for name, test_file in _GATE_FROM_CALLER.items():
        assert (root / test_file).is_file(), f"{name} is exempt on the word of {test_file}"


@pytest.mark.parametrize(
    "client_cls",
    [c for c in _client_classes() if c.__name__ not in _GATE_FROM_CALLER],
    ids=lambda c: c.__name__,
)
def test_a_wb_client_is_paced_once_built(client_cls: type[BaseWBClient]) -> None:
    """With pacing enabled, the built client holds a real bucket, not the null one.

    Stronger than reading the source: it catches a gate wired to a factory that
    returns :class:`NullRateGate` for this surface, which is what «it is in the
    file, so it must be paced» would miss.
    """
    settings = Settings(wb_rate_pacing_enabled=True)
    try:
        client = client_cls(settings, token="probe-token")  # type: ignore[call-arg]
    except TypeError:
        pytest.fail(
            f"{client_cls.__name__} needs more than (settings, token) to build, so "
            "this test cannot check it. If it takes its gate from the caller, list "
            "it in _GATE_FROM_CALLER with a test that checks every caller instead."
        )

    assert not isinstance(client._rate_gate, NullRateGate), (
        f"{client_cls.__name__} builds with NullRateGate even though pacing is on."
    )
