"""Adversarial / stress tests for the JBH Allocation Model.

These tests are deliberately hostile. They feed the model the kind of inputs a
REAL GVT file produces — multi-container cells, all-ports mixed data, missing
optional columns, alternate header spellings, malformed dates, huge volumes,
all-excluded pools, duplicate IDs — and assert the model degrades gracefully
(no crashes, no silently wrong totals) rather than only handling the happy path.

The GVT *is* the Inbound Container Milestone, so the model must consume GVT
shapes directly.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from config.port_allocation_rules import get_port_rules
from optimization.jbh_allocation import run_allocation_model
from optimization.jbh_allocation.eligibility import (
    normalize_columns, explode_container_ids, filter_to_port, filter_eligible,
)
from optimization.jbh_allocation.scheduling import vba_week_number, compute_expected_outgate

TODAY = date(2026, 6, 22)  # a Monday


# ---------------------------------------------------------------------------
# Builders that mimic REAL raw-GVT column names and shapes
# ---------------------------------------------------------------------------

def _gvt_rows(n, port="LAX", **over):
    """n eligible-by-default rows using RAW GVT column names (not canonical)."""
    rows = []
    for i in range(n):
        row = {
            "Discharged Port": port,
            "Terminal": "APM",
            "Facility": "XLA4",
            "SSL": "MAEU",
            "Vessel": f"VESSEL {i % 4}",
            "Category": "CD",
            "Container": f"ABCU{1000000 + i}",
            "Priority": "Priority 2",
            "Dray SCAC(FL)": "HJBT",
            "Ocean ETA": pd.Timestamp("2026-06-23"),
        }
        row.update(over)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Multi-container cells (the #1 real-GVT trap)
# ---------------------------------------------------------------------------

class TestExplodeContainers:
    def test_comma_separated_cell_explodes(self):
        df = pd.DataFrame({"container_id": ["A1, A2, A3", "B1"]})
        out = explode_container_ids(df)
        assert len(out) == 4
        assert set(out["container_id"]) == {"A1", "A2", "A3", "B1"}

    def test_mixed_separators(self):
        df = pd.DataFrame({"container_id": ["A1;A2|A3 A4", "B1\nB2"]})
        out = explode_container_ids(df)
        assert set(out["container_id"]) == {"A1", "A2", "A3", "A4", "B1", "B2"}

    def test_other_columns_duplicated(self):
        df = pd.DataFrame({"container_id": ["A1, A2"], "scac": ["HJBT"], "facility": ["XLA4"]})
        out = explode_container_ids(df)
        assert len(out) == 2
        assert (out["scac"] == "HJBT").all()

    def test_single_id_unchanged(self):
        df = pd.DataFrame({"container_id": ["A1", "A2"]})
        out = explode_container_ids(df)
        assert len(out) == 2

    def test_empty_tokens_dropped(self):
        df = pd.DataFrame({"container_id": ["A1,, ,A2", "  "]})
        out = explode_container_ids(df)
        assert set(out["container_id"]) == {"A1", "A2"}

    def test_nan_cell_dropped(self):
        df = pd.DataFrame({"container_id": [np.nan, "A1"]})
        out = explode_container_ids(df)
        assert set(out["container_id"]) == {"A1"}

    def test_full_model_run_with_multi_container_cells(self):
        # One GVT row holding 30 containers must allocate as 30 containers.
        ids = ", ".join(f"ABCU{2000000+i}" for i in range(30))
        df = _gvt_rows(1, Container=ids)
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert len(res["eligible"]) == 30


# ---------------------------------------------------------------------------
# All-ports GVT: the model must isolate the selected port
# ---------------------------------------------------------------------------

class TestPortIsolation:
    def test_only_selected_port_allocated(self):
        lax = _gvt_rows(10, port="LAX")
        sea = _gvt_rows(10, port="SEA", Container="ZZZ")
        sea["Container"] = [f"SEAU{i}" for i in range(10)]
        bal = _gvt_rows(10, port="BAL")
        bal["Container"] = [f"BALU{i}" for i in range(10)]
        df = pd.concat([lax, sea, bal], ignore_index=True)
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        # 30 total rows in, only the 10 LAX rows considered.
        assert res["port_rows"] == 10
        assert len(res["eligible"]) == 10

    def test_us_prefixed_port_code_matches(self):
        df = _gvt_rows(5, port="USLAX")
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert res["port_rows"] == 5

    def test_no_rows_for_port_is_clean_error(self):
        df = _gvt_rows(5, port="SEA")
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert res["errors"] and "No rows for port" in res["errors"][0]


# ---------------------------------------------------------------------------
# Missing optional columns — GVT often lacks priority / term_avail / actual_pu
# ---------------------------------------------------------------------------

class TestMissingOptionalColumns:
    def test_no_priority_column(self):
        df = _gvt_rows(20).drop(columns=["Priority"])
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert len(res["allocated"]) > 0

    def test_no_term_avail_uses_eta_path(self):
        df = _gvt_rows(20)  # no Term Avail column at all
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert res["eligible"]["expected_outgate"].notna().all()

    def test_no_terminal_uses_ssl_fallback(self):
        df = _gvt_rows(20).drop(columns=["Terminal"])
        res = run_allocation_model(df, "LAX", today=TODAY)
        # SSL fallback fills terminal (no known terminals -> default APM).
        assert not res["errors"]
        assert (res["eligible"]["terminal"].astype(str).str.upper() == "APM").all()

    def test_no_vessel_no_category_still_runs(self):
        df = _gvt_rows(20).drop(columns=["Vessel"])
        df["Category"] = "TL"
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]

    def test_bare_minimum_columns(self):
        # Only the 5 required, nothing else.
        df = pd.DataFrame({
            "Discharged Port": ["LAX"] * 5,
            "Facility": ["XLA4"] * 5,
            "Category": ["CD"] * 5,
            "Container": [f"C{i}" for i in range(5)],
            "Dray SCAC(FL)": ["HJBT"] * 5,
            "Ocean ETA": [pd.Timestamp("2026-06-23")] * 5,
        })
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]


# ---------------------------------------------------------------------------
# Malformed / dirty data
# ---------------------------------------------------------------------------

class TestDirtyData:
    def test_string_dates_parsed(self):
        df = _gvt_rows(10, **{"Ocean ETA": "2026-06-23"})
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert len(res["allocated"]) > 0

    def test_unparseable_dates_excluded_not_crash(self):
        df = _gvt_rows(10)
        df.loc[0:4, "Ocean ETA"] = "not a date"
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        # 5 bad-date rows fall out via the Ocean-ETA-required filter.
        assert len(res["eligible"]) == 5

    def test_mixed_case_and_whitespace_carrier(self):
        df = _gvt_rows(10, **{"Dray SCAC(FL)": "  hjbt  "})
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]

    def test_blank_scac_does_not_crash(self):
        df = _gvt_rows(10, **{"Dray SCAC(FL)": ""})
        res = run_allocation_model(df, "LAX", today=TODAY)
        # Blank SCAC is allowed (container available for new allocation), not excluded.
        assert not res["errors"]

    def test_duplicate_container_ids_kept(self):
        # Real GVT can repeat an ID across rows; the model shouldn't crash or
        # silently collapse them (dedup is a downstream concern).
        df = _gvt_rows(10)
        df["Container"] = "SAMEID0000000"
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]

    def test_all_null_optional_dates(self):
        df = _gvt_rows(10)
        df["Term Avail"] = pd.NaT
        df["Actual PU"] = pd.NaT
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]

    def test_negative_and_weird_priority_values(self):
        df = _gvt_rows(10)
        df["Priority"] = ["Priority 1", "", "Normal", np.nan, "P5",
                          "Priority 3", "URGENT", "0", "-1", "Priority 2"]
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]


# ---------------------------------------------------------------------------
# Eligibility extremes
# ---------------------------------------------------------------------------

class TestEligibilityExtremes:
    def test_all_excluded_yields_clean_error(self):
        df = _gvt_rows(10, Category="Robotics")
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert res["errors"] and "No eligible" in res["errors"][0]
        # Nothing allocated, but the run completed without raising.
        assert "allocated" not in res or res.get("allocated") is None or res["allocated"] is None

    def test_every_filter_fires_at_once(self):
        df = pd.concat([
            _gvt_rows(2, Priority="Express"),
            _gvt_rows(2, Category="Devices"),
            _gvt_rows(2, Facility="DEN2"),
            _gvt_rows(2, Vessel="AIR FREIGHT"),
            _gvt_rows(2, **{"Dray SCAC(FL)": "DNSL"}),
            _gvt_rows(2, **{"Ocean ETA": pd.NaT}),
            _gvt_rows(5),  # the only eligible ones
        ], ignore_index=True)
        # Make container IDs unique across the concat so explode doesn't matter.
        df["Container"] = [f"C{i:07d}" for i in range(len(df))]
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert len(res["eligible"]) == 5
        assert len(res["excluded"]) == 12

    def test_secondary_destinations_only_below_target(self):
        # All secondary-destination containers: kept eligible, flagged for Phase 2.
        df = _gvt_rows(20, Facility="LAX9-S")
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert res["eligible"]["is_secondary_destination"].all()


# ---------------------------------------------------------------------------
# Capacity / volume stress
# ---------------------------------------------------------------------------

class TestVolumeStress:
    def test_large_volume_runs_and_respects_caps(self):
        # 5,000 containers, all this week, all APM/HJBT. The week must never
        # exceed the hard ceiling, and no Sunday allocations.
        df = _gvt_rows(5000)
        df["Container"] = [f"C{i:08d}" for i in range(5000)]
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        alloc = res["allocated"]
        # Per horizon week, total allocated <= hard ceiling.
        rules = get_port_rules("LAX")
        for wk, grp in alloc.groupby("horizon_week"):
            assert len(grp) <= rules.hard_weekly_ceiling
        # No Sunday outgates anywhere.
        assert (alloc["expected_outgate"].dt.weekday != 6).all()

    def test_day_concentration_never_exceeds_hard_cap(self):
        df = _gvt_rows(2000)
        df["Container"] = [f"C{i:08d}" for i in range(2000)]
        res = run_allocation_model(df, "LAX", today=TODAY)
        rules = get_port_rules("LAX")
        alloc = res["allocated"]
        for wk, grp in alloc.groupby("horizon_week"):
            target = res["weeks"][wk]["target"]
            hard = rules.hard_day_cap(target)
            by_day = grp["expected_outgate"].dt.date.value_counts()
            assert (by_day <= hard).all(), f"week {wk}: a day exceeds hard cap {hard}"

    def test_empty_frame(self):
        res = run_allocation_model(pd.DataFrame(), "LAX", today=TODAY)
        assert res["errors"]  # graceful, not a crash

    def test_single_container(self):
        df = _gvt_rows(1)
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert len(res["allocated"]) == 1


# ---------------------------------------------------------------------------
# Horizon behavior
# ---------------------------------------------------------------------------

class TestHorizon:
    def test_containers_outside_horizon_not_allocated(self):
        # ETAs far in the future (beyond the 4-week horizon) -> no week bucket.
        df = _gvt_rows(20, **{"Ocean ETA": pd.Timestamp("2026-12-01")})
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        # Eligible (valid future ETA) but allocated to none of the horizon weeks.
        assert len(res["allocated"]) == 0

    def test_extended_week_flagged(self):
        res = run_allocation_model(_gvt_rows(20), "LAX", today=TODAY)
        weeks = res["horizon_weeks"]
        # Last horizon week is the extended (+3) week.
        assert res["weeks"][weeks[-1]]["is_extended"] is True
        assert res["weeks"][weeks[0]]["is_extended"] is False


# ---------------------------------------------------------------------------
# Alternate header spellings (normalize_columns robustness)
# ---------------------------------------------------------------------------

class TestHeaderAliases:
    def test_container_numbers_header(self):
        df = _gvt_rows(5).rename(columns={"Container": "Container Numbers"})
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]
        assert len(res["eligible"]) == 5

    def test_dray_scac_fl_header(self):
        # 'Dray SCAC(FL)' must map to canonical 'scac'.
        df = normalize_columns(_gvt_rows(3))
        assert "scac" in df.columns

    def test_eta_header_variants(self):
        df = _gvt_rows(5).rename(columns={"Ocean ETA": "ETA"})
        res = run_allocation_model(df, "LAX", today=TODAY)
        assert not res["errors"]


# ---------------------------------------------------------------------------
# Determinism — same input, same output
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_repeatable(self):
        df = _gvt_rows(500)
        df["Container"] = [f"C{i:08d}" for i in range(500)]
        r1 = run_allocation_model(df.copy(), "LAX", today=TODAY)
        r2 = run_allocation_model(df.copy(), "LAX", today=TODAY)
        assert len(r1["allocated"]) == len(r2["allocated"])
        assert list(r1["allocated"]["container_id"]) == list(r2["allocated"]["container_id"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
