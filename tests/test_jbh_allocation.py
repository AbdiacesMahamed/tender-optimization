"""Tests for the JBH Allocation Model.

Validates the engine against the concrete numbers stated in
Allocation_Model_Rules_Reference.docx, plus eligibility, scheduling, and the
port-config layer's "add a new port = add a dict entry" contract.
"""
from datetime import date

import pandas as pd
import pytest

from config.port_allocation_rules import (
    get_port_rules, available_ports, has_port_rules,
    PORT_ALLOCATION_RULES, DEFAULT_RULES,
)
from optimization.jbh_allocation import (
    run_allocation_model, filter_eligible, vba_week_number,
    compute_expected_outgate, compute_terminal_caps, compute_weekly_target,
    normalize_columns,
)


# ---------------------------------------------------------------------------
# Port config layer
# ---------------------------------------------------------------------------

class TestPortConfig:
    def test_lax_present(self):
        assert has_port_rules("LAX")
        assert "LAX" in available_ports()

    def test_case_insensitive(self):
        assert has_port_rules("lax")
        assert get_port_rules("lax").port == "LAX"

    def test_unknown_port_raises_helpful(self):
        with pytest.raises(KeyError, match="No allocation rules configured"):
            get_port_rules("ZZZ")

    def test_defaults_merge(self):
        # LAX doesn't override hard_weekly_ceiling -> inherits the default 345.
        rules = get_port_rules("LAX")
        assert rules.hard_weekly_ceiling == 345
        assert rules.base_weekly_target == 275

    def test_lax_overrides_apply(self):
        rules = get_port_rules("LAX")
        assert rules.strategy_terminals["APM"]["base_pct"] == 0.70
        assert "XLA4" in rules.preferred_facilities
        assert rules.ssl_fallback_default_terminal == "APM"

    def test_adding_a_port_is_a_dict_entry(self):
        # Simulate adding a minimal new port at runtime; it should inherit all
        # defaults and only override what's given. (Mutates module dict, restored.)
        PORT_ALLOCATION_RULES["SEA"] = {"base_weekly_target": 100}
        try:
            rules = get_port_rules("SEA")
            assert rules.base_weekly_target == 100         # override
            assert rules.hard_weekly_ceiling == 345        # inherited default
            assert rules.excluded_carriers == ["DNSL"]     # inherited default
        finally:
            del PORT_ALLOCATION_RULES["SEA"]


# ---------------------------------------------------------------------------
# Section 5.1 — terminal caps must match the doc exactly
# ---------------------------------------------------------------------------

class TestTerminalCaps:
    def test_doc_numbers_at_target_275(self):
        rules = get_port_rules("LAX")
        caps = compute_terminal_caps(275, rules)
        # From the doc: APM 221, TTI 69, TRAPAC 33
        assert caps["APM"] == 221
        assert caps["TTI"] == 69
        assert caps["TRAPAC"] == 33


# ---------------------------------------------------------------------------
# Section 4.1 — weekly target floors at base
# ---------------------------------------------------------------------------

class TestWeeklyTarget:
    def test_floors_at_base(self):
        rules = get_port_rules("LAX")
        df = pd.DataFrame({"category": ["CD"] * 10})
        assert compute_weekly_target(df, rules) >= 275

    def test_empty_returns_base(self):
        rules = get_port_rules("LAX")
        assert compute_weekly_target(pd.DataFrame(), rules) == 275


# ---------------------------------------------------------------------------
# Section 14 — VBA week numbering
# ---------------------------------------------------------------------------

class TestVbaWeekNumber:
    def test_jan1_is_week_1(self):
        assert vba_week_number(date(2026, 1, 1)) == 1

    def test_first_sunday_starts_week_2(self):
        # 2026-01-01 is a Thursday. The first Sunday (Jan 4) starts week 2.
        assert vba_week_number(date(2026, 1, 3)) == 1   # Saturday, still week 1
        assert vba_week_number(date(2026, 1, 4)) == 2   # Sunday -> week 2

    def test_none_and_nat(self):
        assert vba_week_number(None) is None
        assert vba_week_number(pd.NaT) is None


# ---------------------------------------------------------------------------
# Section 2 — eligibility filters
# ---------------------------------------------------------------------------

def _milestone(**overrides):
    """One-row milestone frame with sensible eligible defaults."""
    base = {
        "terminal": "APM", "facility": "XLA4", "ssl": "MAEU",
        "vessel": "EVER GIVEN", "category": "CD", "container_id": "ABCU1234567",
        "priority_code": "Priority 1", "scac": "HJBT",
        "ocean_eta": pd.Timestamp("2026-06-25"), "term_avail": pd.NaT,
        "actual_pu": pd.NaT,
    }
    base.update(overrides)
    return pd.DataFrame([base])


class TestEligibility:
    def setup_method(self):
        self.rules = get_port_rules("LAX")
        self.today = date(2026, 6, 24)

    def test_eligible_passes(self):
        elig, excl = filter_eligible(_milestone(), self.rules, today=self.today)
        assert len(elig) == 1 and excl.empty

    def test_express_excluded(self):
        elig, excl = filter_eligible(_milestone(priority_code="Express"), self.rules, today=self.today)
        assert elig.empty and "Express" in excl.iloc[0]["exclusion_reason"]

    def test_robotics_excluded(self):
        elig, excl = filter_eligible(_milestone(category="Robotics"), self.rules, today=self.today)
        assert elig.empty

    def test_devices_excluded(self):
        elig, _ = filter_eligible(_milestone(category="Devices"), self.rules, today=self.today)
        assert elig.empty

    def test_excluded_destination(self):
        elig, _ = filter_eligible(_milestone(facility="DEN2"), self.rules, today=self.today)
        assert elig.empty

    def test_air_freight_vessel_excluded(self):
        elig, _ = filter_eligible(_milestone(vessel="AIR FREIGHT"), self.rules, today=self.today)
        assert elig.empty

    def test_dnsl_carrier_excluded(self):
        elig, _ = filter_eligible(_milestone(scac="DNSL"), self.rules, today=self.today)
        assert elig.empty

    def test_missing_eta_excluded(self):
        elig, _ = filter_eligible(_milestone(ocean_eta=pd.NaT), self.rules, today=self.today)
        assert elig.empty

    def test_past_eta_excluded(self):
        elig, _ = filter_eligible(_milestone(ocean_eta=pd.Timestamp("2026-06-01")),
                                  self.rules, today=self.today)
        assert elig.empty

    def test_secondary_destination_kept_but_flagged(self):
        elig, _ = filter_eligible(_milestone(facility="LAX9-S"), self.rules, today=self.today)
        # Secondary stays in the eligible pool, flagged for Phase 2.
        assert len(elig) == 1
        assert bool(elig.iloc[0]["is_secondary_destination"]) is True


# ---------------------------------------------------------------------------
# Section 3 — expected outgate
# ---------------------------------------------------------------------------

class TestExpectedOutgate:
    def setup_method(self):
        self.rules = get_port_rules("LAX")

    def test_eta_plus_lead_time(self):
        # APM ETA lead = 3. ETA Mon 2026-06-22 -> Thu 2026-06-25.
        df = _milestone(terminal="APM", ocean_eta=pd.Timestamp("2026-06-22"))
        out = compute_expected_outgate(df, self.rules)
        assert out.iloc[0]["expected_outgate"] == pd.Timestamp("2026-06-25")

    def test_term_avail_takes_priority(self):
        # APM AV lead = 2. term_avail Mon 2026-06-22 -> Wed 2026-06-24,
        # overriding the ETA-based path.
        df = _milestone(terminal="APM", ocean_eta=pd.Timestamp("2026-06-01"),
                        term_avail=pd.Timestamp("2026-06-22"))
        out = compute_expected_outgate(df, self.rules)
        assert out.iloc[0]["expected_outgate"] == pd.Timestamp("2026-06-24")

    def test_apm_friday_eta_offset(self):
        # APM ETA lead = 3 + Friday discharge delay +1 = 4.
        # ETA Fri 2026-06-26 -> +4 = Tue 2026-06-30.
        df = _milestone(terminal="APM", ocean_eta=pd.Timestamp("2026-06-26"))
        out = compute_expected_outgate(df, self.rules)
        assert out.iloc[0]["expected_outgate"] == pd.Timestamp("2026-06-30")

    def test_apm_weekend_shifts_sunday_only(self):
        # TRAPAC (default rules) shifts BOTH weekend days; APM shifts Sunday only.
        # Build an outgate landing on Saturday for both and compare.
        # TRAPAC ETA lead = 2: ETA Thu 2026-06-25 -> Sat 2026-06-27 -> shifts to Mon 06-29.
        trapac = compute_expected_outgate(
            _milestone(terminal="TRAPAC", ocean_eta=pd.Timestamp("2026-06-25")), self.rules)
        assert trapac.iloc[0]["expected_outgate"] == pd.Timestamp("2026-06-29")
        # APM ETA lead = 3: ETA Wed 2026-06-24 -> Sat 2026-06-27 -> APM keeps Saturday.
        apm = compute_expected_outgate(
            _milestone(terminal="APM", ocean_eta=pd.Timestamp("2026-06-24")), self.rules)
        assert apm.iloc[0]["expected_outgate"] == pd.Timestamp("2026-06-27")


# ---------------------------------------------------------------------------
# End-to-end model run
# ---------------------------------------------------------------------------

class TestRunModel:
    def test_unknown_port_returns_error(self):
        res = run_allocation_model(_milestone(), "ZZZ", today=date(2026, 6, 24))
        assert res["errors"] and "No allocation rules" in res["errors"][0]

    def test_missing_columns_error(self):
        res = run_allocation_model(pd.DataFrame({"foo": [1]}), "LAX", today=date(2026, 6, 24))
        assert res["errors"] and "missing required column" in res["errors"][0].lower()

    def test_small_run_allocates(self):
        # 50 eligible HJBT/APM containers, ETA this week -> should allocate.
        rows = []
        for i in range(50):
            rows.append({
                "terminal": "APM", "facility": "XLA4", "ssl": "MAEU",
                "vessel": f"V{i % 3}", "category": "CD",
                "container_id": f"ABCU{1000000 + i}", "priority_code": "Priority 2",
                "scac": "HJBT", "ocean_eta": pd.Timestamp("2026-06-23"),
                "term_avail": pd.NaT, "actual_pu": pd.NaT,
            })
        df = pd.DataFrame(rows)
        res = run_allocation_model(df, "LAX", today=date(2026, 6, 22))
        assert not res["errors"]
        assert len(res["allocated"]) > 0
        # All allocated rows carry a terminal and a pass label.
        assert res["allocated"]["alloc_terminal"].notna().all()
        assert res["allocated"]["alloc_pass"].notna().all()

    def test_sunday_never_allocated(self):
        # Force outgates onto Sunday and confirm none are allocated that day
        # (daily cap Sunday=0). APM keeps Saturday but shifts Sunday to Monday,
        # so we use a backup terminal that shifts both — use PCT (default rules).
        rows = []
        for i in range(10):
            rows.append({
                "terminal": "TRAPAC", "facility": "ONT8", "ssl": "MAEU",
                "vessel": "V1", "category": "CD", "container_id": f"ABCU{2000000+i}",
                "priority_code": "Normal", "scac": "HJBT",
                "ocean_eta": pd.Timestamp("2026-06-26"),  # +2 -> Sunday -> shifts Monday
                "term_avail": pd.NaT, "actual_pu": pd.NaT,
            })
        res = run_allocation_model(pd.DataFrame(rows), "LAX", today=date(2026, 6, 22))
        alloc = res["allocated"]
        if not alloc.empty:
            assert (alloc["expected_outgate"].dt.weekday != 6).all()  # no Sundays


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
