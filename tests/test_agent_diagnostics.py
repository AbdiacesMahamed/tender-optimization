"""
Tests for the assistant's read-only data-diagnostics tools:

  * historic_volume_share — carrier market share over the last N weeks per lane
  * missing_rate_audit     — containers/lanes with no usable rate
  * trace_containers       — locate specific container IDs (no hallucination)

These attack the same way a confused user or hallucinating model would: missing
columns, empty/garbage input, the $0-rate trap, container IDs that don't exist,
and case differences. Everything runs offline — the handlers are pure pandas
over a DataFrame; Streamlit is mocked only because sibling __init__s import it.
"""
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

# Streamlit is stubbed centrally in tests/conftest.py before any first-party import.

from components.chatbot import tools as T


# ==================== fixtures ====================

@pytest.fixture
def data():
    """Two BAL carriers across weeks 32/33, plus an UNRATED ($0) NYC lane."""
    return pd.DataFrame([
        {"Dray SCAC(FL)": "RKNE", "Discharged Port": "BAL", "Facility": "HGR6",
         "Week Number": 32, "Category": "FBA FCL", "Lane": "USBALHGR6",
         "Container Numbers": "C1, C2, C3", "Container Count": 3,
         "Base Rate": 100.0, "Total Rate": 300.0},
        {"Dray SCAC(FL)": "ABCD", "Discharged Port": "BAL", "Facility": "HGR6",
         "Week Number": 33, "Category": "FBA FCL", "Lane": "USBALHGR6",
         "Container Numbers": "C4", "Container Count": 1,
         "Base Rate": 80.0, "Total Rate": 80.0},
        {"Dray SCAC(FL)": "HJBT", "Discharged Port": "NYC", "Facility": "EWR9",
         "Week Number": 33, "Category": "Retail CD", "Lane": "USNYCEWR9",
         "Container Numbers": "C5, C6", "Container Count": 2,
         "Base Rate": 0.0, "Total Rate": 0.0},
    ])


# ==================== historic_volume_share ====================

def test_volume_share_basic(data):
    out = T.historic_volume_share(data, n_weeks=5)
    assert "error" not in out
    rows = {(r["carrier"], r["lane"]): r for r in out["rows"]}
    # RKNE has 3 of 4 BAL containers across the window -> 75% of that lane.
    assert rows[("RKNE", "USBALHGR6")]["volume_share_pct"] == 75
    assert rows[("ABCD", "USBALHGR6")]["volume_share_pct"] == 25
    # HJBT is the only NYC carrier -> 100%.
    assert rows[("HJBT", "USNYCEWR9")]["volume_share_pct"] == 100


def test_volume_share_scoped(data):
    out = T.historic_volume_share(data, {"carriers": ["RKNE"]}, n_weeks=5)
    carriers = {r["carrier"] for r in out["rows"]}
    assert carriers == {"RKNE"}


def test_volume_share_missing_columns(data):
    no_lane = data.drop(columns=["Lane"])
    out = T.historic_volume_share(no_lane)
    assert "error" in out and "Lane" in out["error"]


def test_volume_share_no_data():
    assert "error" in T.historic_volume_share(None)
    assert "error" in T.historic_volume_share(pd.DataFrame())


def test_volume_share_scope_matches_nothing(data):
    out = T.historic_volume_share(data, {"carriers": ["ZZZZ"]})
    assert out["rows"] == []
    assert "note" in out


def test_volume_share_does_not_mutate(data):
    before = data.copy()
    T.historic_volume_share(data, n_weeks=5)
    assert_frame_equal(data, before)


# ==================== missing_rate_audit ====================

def test_missing_rate_audit_finds_zero_rate(data):
    out = T.missing_rate_audit(data)
    assert out["has_missing_rates"] is True
    assert out["affected_containers"] == 2          # the two HJBT/NYC containers
    assert out["affected_pct"] == pytest.approx(33.33, abs=0.01)
    carriers = {c["carrier"] for c in out["by_carrier"]}
    assert carriers == {"HJBT"}
    lanes = {l["lane"] for l in out["by_lane"]}
    assert lanes == {"USNYCEWR9"}


def test_missing_rate_audit_clean(data):
    clean = data[data["Base Rate"] > 0].copy()
    out = T.missing_rate_audit(clean)
    assert out["has_missing_rates"] is False
    assert out["affected_containers"] == 0


def test_missing_rate_audit_nan_rate(data):
    d = data.copy()
    d.loc[d["Dray SCAC(FL)"] == "ABCD", "Base Rate"] = float("nan")
    out = T.missing_rate_audit(d)
    # ABCD's 1 + HJBT's 2 = 3 affected.
    assert out["affected_containers"] == 3


def test_missing_rate_audit_no_rate_column(data):
    out = T.missing_rate_audit(data.drop(columns=["Base Rate"]))
    assert "error" in out


def test_missing_rate_audit_does_not_mutate(data):
    before = data.copy()
    T.missing_rate_audit(data)
    assert_frame_equal(data, before)


# ==================== trace_containers ====================

def test_trace_finds_and_reports_context(data):
    out = T.trace_containers(data, ["C1"])
    assert out["found_count"] == 1
    rec = out["found"][0]
    assert rec["carrier"] == "RKNE"
    assert rec["lane"] == "USBALHGR6"
    assert rec["week"] == 32
    assert rec["port"] == "BAL"


def test_trace_case_insensitive(data):
    out = T.trace_containers(data, ["c5"])
    assert out["found_count"] == 1
    assert out["found"][0]["carrier"] == "HJBT"


def test_trace_unknown_id_not_invented(data):
    out = T.trace_containers(data, ["C1", "GHOST999"])
    assert out["found_count"] == 1
    assert out["not_found"] == ["GHOST999"]
    # The ghost ID must NOT appear in found.
    assert all(r["container"] != "GHOST999" for r in out["found"])


def test_trace_accepts_scalar(data):
    out = T.trace_containers(data, "C4")
    assert out["found_count"] == 1
    assert out["found"][0]["carrier"] == "ABCD"


def test_trace_empty_and_missing_column(data):
    assert "error" in T.trace_containers(data, [])
    assert "error" in T.trace_containers(data.drop(columns=["Container Numbers"]), ["C1"])
    assert "error" in T.trace_containers(None, ["C1"])


def test_trace_does_not_mutate(data):
    before = data.copy()
    T.trace_containers(data, ["C1", "C5"])
    assert_frame_equal(data, before)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
