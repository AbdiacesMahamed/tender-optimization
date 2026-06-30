"""Tests for prebuilt per-port constraints (components/constraints/prebuilt.py)."""
import os
import pandas as pd
import pytest

from components.constraints import prebuilt
from components.constraints.prebuilt import (
    load_prebuilt_constraints, merge_prebuilt_first, SOURCE_COLUMN,
)

_DIR = prebuilt._DIR


def _write_port_csv(port, body):
    path = os.path.join(_DIR, f"{port}.csv")
    with open(path, "w", newline="") as fh:
        fh.write(body)
    return path


def _header_only(port):
    header = ("Priority Score,Carrier,Category,Lane,Port,Week Number,Day of Week,"
              "Terminal,SSL,Vessel,Maximum Container Count,Minimum Container Count,"
              "Percent Allocation,Excluded FC\n")
    _write_port_csv(port, header)


@pytest.fixture(autouse=True)
def restore_lax():
    """Snapshot LAX.csv and toggles, restore them after each test.

    Also isolates to LAX-only for the duration so the LAX-focused tests below
    are not perturbed by other shipped port CSVs (e.g. SEA/TIW). Tests that need
    another port re-enable it explicitly via ``prebuilt.ENABLED``.
    """
    path = os.path.join(_DIR, "LAX.csv")
    original = open(path).read() if os.path.exists(path) else None
    enabled = dict(prebuilt.ENABLED)
    master = prebuilt.PREBUILT_CONSTRAINTS_ENABLED
    for port in prebuilt.ENABLED:
        prebuilt.ENABLED[port] = (port == "LAX")
    yield
    prebuilt.ENABLED.clear()
    prebuilt.ENABLED.update(enabled)
    prebuilt.PREBUILT_CONSTRAINTS_ENABLED = master
    if original is not None:
        with open(path, "w", newline="") as fh:
            fh.write(original)


def test_header_only_is_noop():
    _header_only("LAX")
    assert len(load_prebuilt_constraints()) == 0


def test_loads_rows_and_tags_source():
    _write_port_csv("LAX", "Priority Score,Carrier,Port,Maximum Container Count\n5,ATMI,LAX,50\n")
    df = load_prebuilt_constraints()
    assert len(df) == 1
    assert df.iloc[0][SOURCE_COLUMN] == "Prebuilt:LAX"
    assert df.iloc[0]["Maximum Container Count"] == 50


def test_master_switch_off_disables_all():
    _write_port_csv("LAX", "Priority Score,Carrier,Port\n5,ATMI,LAX\n")
    prebuilt.PREBUILT_CONSTRAINTS_ENABLED = False
    assert len(load_prebuilt_constraints()) == 0


def test_per_port_switch_off_skips_port():
    _write_port_csv("LAX", "Priority Score,Carrier,Port\n5,ATMI,LAX\n")
    prebuilt.ENABLED["LAX"] = False
    assert len(load_prebuilt_constraints()) == 0


def test_prebuilt_stays_ahead_of_higher_priority_user_rule():
    _write_port_csv("LAX", "Priority Score,Carrier,Port,Maximum Container Count\n5,ATMI,LAX,50\n")
    user = pd.DataFrame({"Priority Score": [999], "Carrier": ["FRQT"], "Port": ["LAX"]})
    merged = merge_prebuilt_first(user)
    # Prebuilt (priority 5) must precede the user rule (priority 999).
    assert merged.iloc[0][SOURCE_COLUMN] == "Prebuilt:LAX"
    assert merged.iloc[1][SOURCE_COLUMN] == "User"


def test_merge_with_no_user_constraints():
    _write_port_csv("LAX", "Priority Score,Carrier,Port\n5,ATMI,LAX\n")
    merged = merge_prebuilt_first(None)
    assert len(merged) == 1
    assert merged.iloc[0][SOURCE_COLUMN] == "Prebuilt:LAX"


def test_merge_with_no_prebuilt_returns_user_unchanged():
    _header_only("LAX")
    prebuilt.PREBUILT_CONSTRAINTS_ENABLED = False
    user = pd.DataFrame({"Priority Score": [10], "Carrier": ["FRQT"]})
    merged = merge_prebuilt_first(user)
    assert len(merged) == 1
    assert merged.iloc[0]["Carrier"] == "FRQT"


# ---------------------------------------------------------------------------
# PNW waterfront carrier-to-port lockouts (SEA = Seattle, TIW = Tacoma).
# These rules ship as real config CSVs, so assert the actual files encode the
# business rule: a carrier "only at" one port is locked out (Max 0) of the other.
# ---------------------------------------------------------------------------

def _pnw_rows(port):
    """Load the shipped per-port CSV and return its lockout rows."""
    prebuilt.ENABLED[port] = True
    df = load_prebuilt_constraints()
    return df[df[SOURCE_COLUMN] == f"Prebuilt:{port}"]


def test_tiw_locks_out_seattle_only_carriers():
    """Waterfront (AOYV) and RoadEx (RDXY) are Seattle-only -> Max 0 at TIW."""
    rows = _pnw_rows("TIW")
    locked = set(rows[rows["Maximum Container Count"] == 0]["Carrier"])
    assert {"AOYV", "RDXY"}.issubset(locked)
    # All TIW prebuilt rows are scoped to the TIW port.
    assert (rows["Port"] == "TIW").all()


def test_sea_locks_out_tacoma_only_carriers():
    """RoadOne (RKNE) and JB Hunt (HJBT) are Tacoma-only -> Max 0 at SEA."""
    rows = _pnw_rows("SEA")
    locked = set(rows[rows["Maximum Container Count"] == 0]["Carrier"])
    assert {"RKNE", "HJBT"}.issubset(locked)
    assert (rows["Port"] == "SEA").all()
