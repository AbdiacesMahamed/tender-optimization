"""Tests for PNW vessel-level allocation rules (Rules 1-4).

Covers the data-derived constraint-row generators (Rule 1: Hunt exactly 130/wk at
TIW; Rule 2: no SCAC over 60/vessel) and the post-allocation one-vessel-per-carrier
enforcement (Rules 3 & 4), plus end-to-end enforcement through the real constraint
engine for the per-vessel cap.
"""
import pandas as pd
import pytest

from components.constraints.pnw_vessel_rules import (
    build_hunt_weekly_rows, build_per_vessel_cap_rows, build_pnw_constraint_rows,
    check_one_vessel_per_carrier, enforce_one_vessel_per_carrier,
    enforce_one_vessel_per_carrier_across,
    check_per_vessel_cap, enforce_per_vessel_cap_across,
    HUNT_SCAC, HUNT_PORT, HUNT_WEEKLY_MAX, PER_VESSEL_MAX,
)
from components.constraints.processor import (
    apply_constraints_to_data, expected_constraint_columns,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _alloc_row(carrier, vessel, port, eta, ids, week=26):
    """One allocated per-container-group row."""
    id_list = list(ids)
    return {
        "Dray SCAC(FL)": carrier,
        "Vessel": vessel,
        "Discharged Port": port,
        "Ocean ETA": pd.Timestamp(eta),
        "Week Number": week,
        "Container Numbers": ", ".join(id_list),
        "Container Count": len(id_list),
        "Lane": f"US{port}ABC1",
        "Base Rate": 100.0,
    }


def _ids(prefix, n):
    return [f"{prefix}{i:03d}" for i in range(n)]


# ---------------------------------------------------------------------------
# Rule 1 — Hunt exactly 130/week at Tacoma
# ---------------------------------------------------------------------------

def test_hunt_rows_one_max_per_tiw_week():
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "TIW", "2026-06-22", _ids("A", 5), week=26),
        _alloc_row("FRQT", "VES A", "TIW", "2026-06-29", _ids("B", 5), week=27),
        _alloc_row("HJBT", "VES C", "SEA", "2026-06-22", _ids("C", 5), week=26),  # SEA, ignored
    ])
    rows = build_hunt_weekly_rows(data)
    # Weeks present at TIW: 26 and 27 -> ONE Max-130 row each (no Min floor now:
    # HJBT is capped at up to 130 and allocated first, not forced to exactly 130).
    assert len(rows) == 2
    assert set(rows["Week Number"]) == {26, 27}
    assert (rows["Carrier"] == HUNT_SCAC).all()
    assert (rows["Port"] == HUNT_PORT).all()
    assert (rows["Maximum Container Count"] == HUNT_WEEKLY_MAX).all()
    # No Minimum floor is emitted anymore.
    assert rows["Minimum Container Count"].isna().all()


def test_hunt_rows_empty_without_tiw_data():
    data = pd.DataFrame([_alloc_row("HJBT", "VES A", "SEA", "2026-06-22", _ids("A", 5))])
    assert len(build_hunt_weekly_rows(data)) == 0


# ---------------------------------------------------------------------------
# Rule 2 — no SCAC over 60 per vessel
# ---------------------------------------------------------------------------

def test_per_vessel_cap_one_row_per_carrier_vessel():
    # Use carriers NOT locked out of each port: HJBT/FRQT at TIW, AOYV/FRQT at SEA.
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "TIW", "2026-06-22", _ids("A", 70)),
        _alloc_row("FRQT", "VES A", "TIW", "2026-06-22", _ids("B", 10)),
        _alloc_row("AOYV", "VES B", "SEA", "2026-06-22", _ids("C", 5)),
        _alloc_row("FRQT", "VES B", "SEA", "2026-06-22", _ids("D", 5)),
    ])
    rows = build_per_vessel_cap_rows(data)
    # 4 distinct (port, vessel, carrier) combos -> 4 capped rows.
    assert len(rows) == 4
    assert (rows["Maximum Container Count"] == PER_VESSEL_MAX).all()
    assert set(zip(rows["Carrier"], rows["Vessel"])) == {
        ("HJBT", "VES A"), ("FRQT", "VES A"), ("AOYV", "VES B"), ("FRQT", "VES B"),
    }


def test_per_vessel_cap_dedupes_repeated_combo():
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "TIW", "2026-06-22", _ids("A", 40), week=26),
        _alloc_row("HJBT", "VES A", "TIW", "2026-06-29", _ids("B", 40), week=27),
    ])
    rows = build_per_vessel_cap_rows(data)
    assert len(rows) == 1  # same (port, vessel, carrier) collapses to one cap row


def test_per_vessel_cap_ignores_non_pnw():
    data = pd.DataFrame([_alloc_row("HJBT", "VES A", "LAX", "2026-06-22", _ids("A", 70))])
    assert len(build_per_vessel_cap_rows(data)) == 0


def test_per_vessel_cap_enforced_end_to_end():
    """The generated Max-60 row actually caps the carrier through the real engine."""
    data = pd.DataFrame([_alloc_row("HJBT", "VIENNA", "TIW", "2026-06-22", _ids("A", 80))])
    rows = build_per_vessel_cap_rows(data)
    constrained, unconstrained, summary, *_ = apply_constraints_to_data(
        data.copy(), rows, pd.DataFrame()
    )
    # HJBT may keep at most 60 on the vessel across constrained + unconstrained.
    def _hjbt_on_vessel(df):
        if df is None or len(df) == 0:
            return 0
        sub = df[(df["Dray SCAC(FL)"].astype(str) == "HJBT")
                 & (df["Vessel"].astype(str) == "VIENNA")]
        return int(sub["Container Count"].sum()) if len(sub) else 0
    assert _hjbt_on_vessel(constrained) <= PER_VESSEL_MAX
    # Constrained side should hold exactly the cap (the rest goes unconstrained / re-homed).
    assert _hjbt_on_vessel(constrained) == PER_VESSEL_MAX


# ---------------------------------------------------------------------------
# Rules 3 & 4 — one vessel per carrier among same-day arrivals
# ---------------------------------------------------------------------------

def test_no_violation_when_single_vessel_per_day():
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "SEA", "2026-07-06", _ids("A", 10)),
        _alloc_row("FRQT", "VES A", "SEA", "2026-07-06", _ids("B", 10)),
    ])
    assert check_one_vessel_per_carrier(data) == []
    fixed, changes = enforce_one_vessel_per_carrier(data)
    assert changes == []


def test_detects_and_fixes_same_day_two_vessel_split():
    # Two vessels arrive the same day at SEA; HJBT draws from both -> violation.
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "SEA", "2026-07-06", _ids("A", 30)),   # keep (bigger)
        _alloc_row("HJBT", "VES B", "SEA", "2026-07-06", _ids("B", 12)),   # release
        _alloc_row("FRQT", "VES B", "SEA", "2026-07-06", _ids("F", 8)),    # FRQT only 1 vessel
    ])
    viols = check_one_vessel_per_carrier(data)
    assert len(viols) == 1
    assert viols[0]["carrier"] == "HJBT"
    assert viols[0]["kept_vessel"] == "VES A"

    fixed, changes = enforce_one_vessel_per_carrier(data)
    # 12 containers released off VES B for HJBT.
    assert sum(c["containers"] for c in changes) == 12
    # HJBT now draws from a single vessel among the same-day arrivals.
    hjbt = fixed[fixed["Dray SCAC(FL)"].astype(str) == "HJBT"]
    hjbt = hjbt[hjbt["Container Count"] > 0]
    assert set(hjbt["Vessel"]) == {"VES A"}
    # The released row had its carrier cleared (re-homed by optimizer downstream).
    released = fixed[(fixed["Vessel"] == "VES B")
                     & (fixed["Container Numbers"].str.startswith("B"))]
    assert (released["Dray SCAC(FL)"].astype(str).str.strip() == "").all()
    # Volume conserved (no rows dropped).
    assert int(fixed["Container Count"].sum()) == int(data["Container Count"].sum())


def test_no_op_when_vessels_on_different_days():
    # HJBT draws from two vessels, but they arrive on DIFFERENT days -> allowed.
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "SEA", "2026-07-06", _ids("A", 30)),
        _alloc_row("HJBT", "VES B", "SEA", "2026-07-07", _ids("B", 12)),
    ])
    assert check_one_vessel_per_carrier(data) == []
    _, changes = enforce_one_vessel_per_carrier(data)
    assert changes == []


def test_non_pnw_ports_untouched():
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "LAX", "2026-07-06", _ids("A", 30)),
        _alloc_row("HJBT", "VES B", "LAX", "2026-07-06", _ids("B", 12)),
    ])
    assert check_one_vessel_per_carrier(data) == []
    _, changes = enforce_one_vessel_per_carrier(data)
    assert changes == []


def test_combined_generator_has_both_rule_sets():
    data = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "TIW", "2026-06-22", _ids("A", 70), week=26),
        _alloc_row("FRQT", "VES A", "TIW", "2026-06-22", _ids("B", 10), week=26),
    ])
    rows = build_pnw_constraint_rows(data)
    assert set(rows.columns) == set(expected_constraint_columns())
    # Has Hunt weekly rows (min+max for week 26) AND per-vessel caps.
    has_hunt = ((rows["Carrier"] == "HJBT") & (rows["Week Number"] == 26)).any()
    has_cap = (rows["Maximum Container Count"] == PER_VESSEL_MAX).any()
    assert has_hunt and has_cap


def test_empty_inputs_safe():
    empty = pd.DataFrame()
    assert len(build_pnw_constraint_rows(empty)) == 0
    assert check_one_vessel_per_carrier(empty) == []
    fixed, changes = enforce_one_vessel_per_carrier(empty)
    assert changes == []


# ---------------------------------------------------------------------------
# Regression: Rule 2 generator must not emit caps for locked-out carriers
# (Max-60 "permission" would contradict the Max-0 Rule-0 lockout).
# ---------------------------------------------------------------------------

def test_per_vessel_cap_skips_locked_out_carriers():
    data = pd.DataFrame([
        _alloc_row("RKNE", "VES A", "SEA", "2026-06-22", _ids("A", 70)),  # RKNE banned @ SEA
        _alloc_row("HJBT", "VES A", "SEA", "2026-06-22", _ids("B", 70)),  # HJBT banned @ SEA
        _alloc_row("AOYV", "VES B", "TIW", "2026-06-22", _ids("C", 70)),  # AOYV banned @ TIW
        _alloc_row("FRQT", "VES A", "SEA", "2026-06-22", _ids("D", 70)),  # FRQT allowed
    ])
    rows = build_per_vessel_cap_rows(data)
    combos = set(zip(rows["Carrier"], rows["Port"]))
    assert ("RKNE", "SEA") not in combos
    assert ("HJBT", "SEA") not in combos
    assert ("AOYV", "TIW") not in combos
    assert ("FRQT", "SEA") in combos  # the one non-locked carrier still gets a cap


# ---------------------------------------------------------------------------
# Regression: lockout holds across the UNCONSTRAINED table (Rule 0 end-to-end).
# A carrier's ORIGINAL containers at a port it's banned from must be stripped,
# not left sitting on it in the unconstrained remainder.
# ---------------------------------------------------------------------------

def test_lockout_strips_original_carrier_from_unconstrained():
    # RKNE has volume already at SEA (where it is locked out). After applying the
    # SEA lockout, no RKNE should remain at SEA in either table.
    data = pd.DataFrame([
        _alloc_row("RKNE", "VES A", "SEA", "2026-06-22", _ids("A", 30)),
        _alloc_row("FRQT", "VES A", "SEA", "2026-06-22", _ids("B", 20)),
    ])
    lockout = pd.DataFrame([{
        **{c: None for c in expected_constraint_columns()},
        "Carrier": "RKNE", "Port": "SEA", "Maximum Container Count": 0,
        "Priority Score": 100,
    }])
    constrained, unconstrained, *_ = apply_constraints_to_data(
        data.copy(), lockout, pd.DataFrame())
    full = pd.concat([d for d in (constrained, unconstrained) if len(d)], ignore_index=True)
    rkne_sea = full[(full["Discharged Port"] == "SEA")
                    & (full["Dray SCAC(FL)"].astype(str).str.strip() == "RKNE")]
    assert int(rkne_sea["Container Count"].sum()) == 0


# ---------------------------------------------------------------------------
# Rule 2 post-allocation safety net (across tables)
# ---------------------------------------------------------------------------

def test_per_vessel_cap_across_trims_over_cap():
    # ATMI moved onto a vessel post-allocation: 100 on one vessel, split across tables.
    constrained = pd.DataFrame([
        _alloc_row("ATMI", "VES A", "TIW", "2026-06-22", _ids("A", 40)),
    ])
    unconstrained = pd.DataFrame([
        _alloc_row("ATMI", "VES A", "TIW", "2026-06-22", _ids("B", 60)),
    ])
    assert check_per_vessel_cap(pd.concat([constrained, unconstrained],
                                          ignore_index=True))[0]["containers"] == 100
    new_c, new_u, changes = enforce_per_vessel_cap_across(constrained, unconstrained)
    full = pd.concat([d for d in (new_c, new_u) if len(d)], ignore_index=True)
    atmi = full[full["Dray SCAC(FL)"].astype(str).str.strip() == "ATMI"]
    # ATMI kept at most 60 on the vessel; 40 cleared (carrier blanked).
    assert int(atmi["Container Count"].sum()) == 60
    assert sum(c["containers"] for c in changes) == 40
    # Volume conserved across both tables.
    assert int(full["Container Count"].sum()) == 100


def test_per_vessel_cap_across_noop_when_within_cap():
    constrained = pd.DataFrame([_alloc_row("ATMI", "VES A", "TIW", "2026-06-22", _ids("A", 40))])
    unconstrained = pd.DataFrame([_alloc_row("ATMI", "VES A", "TIW", "2026-06-22", _ids("B", 15))])
    _, _, changes = enforce_per_vessel_cap_across(constrained, unconstrained)
    assert changes == []


# ---------------------------------------------------------------------------
# Rules 3/4 across tables — catches a split that spans constrained + unconstrained
# ---------------------------------------------------------------------------

def test_one_vessel_across_catches_cross_table_split():
    # HJBT on VES A (constrained) and VES B (unconstrained), same day at SEA.
    constrained = pd.DataFrame([
        _alloc_row("HJBT", "VES A", "SEA", "2026-07-06", _ids("A", 30)),
    ])
    unconstrained = pd.DataFrame([
        _alloc_row("HJBT", "VES B", "SEA", "2026-07-06", _ids("B", 12)),
    ])
    # Neither table alone is a violation; combined it is.
    assert check_one_vessel_per_carrier(constrained) == []
    assert check_one_vessel_per_carrier(unconstrained) == []
    new_c, new_u, changes = enforce_one_vessel_per_carrier_across(constrained, unconstrained)
    full = pd.concat([d for d in (new_c, new_u) if len(d)], ignore_index=True)
    assert check_one_vessel_per_carrier(full) == []
    assert sum(c["containers"] for c in changes) == 12
    # The kept vessel (VES A, the bigger) stays; VES B volume is cleared.
    hjbt = full[(full["Dray SCAC(FL)"].astype(str).str.strip() == "HJBT")
                & (full["Container Count"] > 0)]
    assert set(hjbt["Vessel"]) == {"VES A"}
    assert int(full["Container Count"].sum()) == 42  # volume conserved


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
