"""A guide capture on a host a harvest also uses must queue in that harvest's bucket.

``WBReferenceClient`` takes its gate from the caller, so the client-wide pacing
test cannot build it and used to skip it. That skip hid exactly the drift the
pacing test exists for: the pallet and return tariffs are captured on the
`common` host, a harvest used that host too at the time, and the captures ran
with no gate at all.

The shared hosts are derived from the clients package rather than listed, so a
harvest moving onto a new host is covered without anyone remembering this file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.core.config import Settings
from src.integrations.wildberries import clients as clients_pkg
from src.integrations.wildberries.rate_limit import NullRateGate
from src.modules.guide.services.capture import _gate_for
from src.modules.guide.sources import GUIDE_SOURCES, GuideSource

_HOST_SETTING = re.compile(r"settings\.(wb_[a-z_]+_base_url)")


def _hosts_a_harvest_uses() -> set[str]:
    """Every host setting named by a WB client other than the guide's own."""
    hosts: set[str] = set()
    for path in Path(clients_pkg.__path__[0]).glob("*.py"):
        if path.name != "reference.py":
            hosts.update(_HOST_SETTING.findall(path.read_text()))
    return hosts


_SHARED = [s for s in GUIDE_SOURCES if s.base_url in _hosts_a_harvest_uses()]


def test_the_scan_finds_the_hosts_and_the_sources_on_them() -> None:
    """A derivation that matches nothing would pass every case below by having none."""
    assert {"wb_analytics_base_url", "wb_statistics_base_url"} <= _hosts_a_harvest_uses()
    assert _SHARED


@pytest.mark.parametrize("source", _SHARED, ids=lambda s: s.key)
def test_a_capture_on_a_harvest_host_is_paced(source: GuideSource) -> None:
    """With pacing on, the gate handed to the reference client is a real bucket."""
    gate = _gate_for(source, token="probe-token", config=Settings(wb_rate_pacing_enabled=True))

    assert not isinstance(gate, NullRateGate), (
        f"{source.key} calls {source.base_url}, which a harvest also uses, with no "
        "gate. Add the host to _SHARED_GATES in src/modules/guide/services/capture.py."
    )
