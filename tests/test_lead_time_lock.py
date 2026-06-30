"""Tests for the lead-time allocation lock (freeze carrier within 3 days of ETA).

Rule: a container whose Ocean ETA is within LEAD_TIME_DAYS (3) of "today" can no
longer be flipped — it is moved from the scenario-eligible (unconstrained) pool
into the frozen (constrained) pool. "Day minus 3" means the deadline is ETA-3:
once (ETA - 3 < today) the row locks, so containers arriving in <3 days, today, or
in the past are all locked; a container 3+ days out stays free.
"""
from datetime import date

import pandas as pd
import pytest

from components.constraints.lead_time_lock import (
    LEAD_TIME_DAYS,
    apply_lead_time_lock,
    lead_time_lock_mask,
)

TODAY = date(2026, 6, 30)


def _frame(etas, carriers=None, counts=None):
    n = len(etas)
    return pd.DataFrame({
        "Ocean ETA": pd.to_datetime(etas),
        "Dray SCAC(FL)": carriers or [f"C{i}" for i in range(n)],
        "Container Count": counts or [1] * n,
        "Container Numbers": [f"CN{i}" for i in range(n)],
    })


class TestMask:
    def test_within_window_locked(self):
        # ETA today, +1, +2 → all locked (ETA - 3 < today).
        df = _frame(["2026-06-30", "2026-07-01", "2026-07-02"])
        assert lead_time_lock_mask(df, today=TODAY).tolist() == [True, True, True]

    def test_boundary_exactly_three_days_out_is_free(self):
        # ETA = today + 3 → ETA - 3 == today, NOT < today → free.
        df = _frame(["2026-07-03"])
        assert lead_time_lock_mask(df, today=TODAY).tolist() == [False]

    def test_four_days_out_is_free(self):
        df = _frame(["2026-07-04", "2026-08-01"])
        assert lead_time_lock_mask(df, today=TODAY).tolist() == [False, False]

    def test_past_eta_is_locked(self):
        df = _frame(["2026-06-29", "2026-01-01"])
        assert lead_time_lock_mask(df, today=TODAY).tolist() == [True, True]

    def test_unparseable_eta_not_locked(self):
        df = _frame(["2026-06-30"])
        df.loc[0, "Ocean ETA"] = pd.NaT
        assert lead_time_lock_mask(df, today=TODAY).tolist() == [False]

    def test_empty_or_missing_column(self):
        assert lead_time_lock_mask(pd.DataFrame(), today=TODAY).tolist() == []
        no_eta = pd.DataFrame({"Dray SCAC(FL)": ["A"]})
        assert lead_time_lock_mask(no_eta, today=TODAY).tolist() == [False]


class TestApply:
    def test_locked_rows_move_to_constrained(self):
        unc = _frame(
            ["2026-07-01", "2026-07-10"],  # first locked, second free
            carriers=["LOCKME", "FREE"],
            counts=[5, 8],
        )
        con = pd.DataFrame(columns=unc.columns)
        new_c, new_u, locked = apply_lead_time_lock(con, unc, today=TODAY)

        assert locked == 5
        assert new_c["Dray SCAC(FL)"].tolist() == ["LOCKME"]
        assert new_u["Dray SCAC(FL)"].tolist() == ["FREE"]

    def test_volume_conserved(self):
        unc = _frame(["2026-06-30", "2026-07-01", "2026-08-01"], counts=[3, 4, 5])
        con = _frame(["2026-12-01"], carriers=["PRELOCKED"], counts=[9])
        new_c, new_u, _ = apply_lead_time_lock(con, unc, today=TODAY)

        total_before = unc["Container Count"].sum() + con["Container Count"].sum()
        total_after = new_c["Container Count"].sum() + new_u["Container Count"].sum()
        assert total_after == total_before

    def test_existing_constrained_rows_preserved(self):
        unc = _frame(["2026-07-01"], carriers=["LOCKME"], counts=[2])
        con = _frame(["2026-12-01"], carriers=["ALREADY"], counts=[7])
        new_c, _, locked = apply_lead_time_lock(con, unc, today=TODAY)

        assert locked == 2
        assert set(new_c["Dray SCAC(FL)"]) == {"ALREADY", "LOCKME"}

    def test_nothing_in_window_is_a_noop(self):
        unc = _frame(["2026-08-01", "2026-09-01"], counts=[1, 1])
        con = pd.DataFrame(columns=unc.columns)
        new_c, new_u, locked = apply_lead_time_lock(con, unc, today=TODAY)

        assert locked == 0
        assert len(new_c) == 0
        assert len(new_u) == 2

    def test_none_pools_handled(self):
        unc = _frame(["2026-07-01"], carriers=["LOCKME"], counts=[1])
        new_c, new_u, locked = apply_lead_time_lock(None, unc, today=TODAY)
        assert locked == 1
        assert new_c["Dray SCAC(FL)"].tolist() == ["LOCKME"]
        assert len(new_u) == 0

    def test_carrier_is_unchanged_when_locked(self):
        # The whole point: the locked row keeps its ORIGINAL carrier (no flip).
        unc = _frame(["2026-07-01"], carriers=["ORIGINALSCAC"], counts=[1])
        new_c, _, _ = apply_lead_time_lock(pd.DataFrame(columns=unc.columns), unc, today=TODAY)
        assert new_c["Dray SCAC(FL)"].iloc[0] == "ORIGINALSCAC"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
