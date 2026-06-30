"""Tests for round-robin even weekly (day-of-week) distribution AND for scope
(vessel / terminal / port) combined with Minimum / Maximum / Percent.

Even distribution: a constraint's allocated containers should be spread across the
week by each row's Ocean ETA weekday — with Friday, Saturday and Sunday collapsed
into one bucket — instead of draining the earliest day first.

Scoping: a scoped Min/Max/Percent must be respected on BOTH the constrained and
unconstrained tables. "Only 40 on a vessel" means HJBT total on that vessel <= 40
across the whole pipeline.
"""
import pandas as pd
import pytest

# Streamlit is stubbed centrally in tests/conftest.py before any first-party import.

from components.constraints.processor import (
    apply_constraints_to_data,
    day_bucket,
    round_robin_quota,
)


def _make_constraint(**fields):
    base = {
        'Priority Score': 10, 'Carrier': None,
        'Maximum Container Count': None, 'Minimum Container Count': None,
        'Percent Allocation': None, 'Category': None, 'Lane': None, 'Port': None,
        'Week Number': None, 'Day of Week': None, 'Terminal': None, 'SSL': None,
        'Vessel': None, 'Excluded FC': None,
    }
    base.update(fields)
    return pd.DataFrame([base])


# ==================== round-robin quota helper ====================

class TestRoundRobinQuotaHelper:
    def test_splits_evenly_across_buckets(self):
        caps = {'Mon': 10, 'Tue': 10, 'Wed': 10, 'Thu': 10, 'Fri-Sun': 10}
        q = round_robin_quota(10, caps)
        assert sum(q.values()) == 10
        assert all(v == 2 for v in q.values()), q

    def test_overflow_cycles_to_buckets_with_room(self):
        # Thin Mon bucket (1) — overflow must land on the others, not be lost.
        caps = {'Mon': 1, 'Tue': 10, 'Wed': 10}
        q = round_robin_quota(9, caps)
        assert sum(q.values()) == 9
        assert q['Mon'] == 1
        assert q['Tue'] + q['Wed'] == 8

    def test_never_exceeds_total_available(self):
        q = round_robin_quota(100, {'Mon': 2, 'Tue': 2})
        assert sum(q.values()) == 4

    def test_day_bucket_collapses_weekend(self):
        assert day_bucket(2) == 'Mon'
        assert day_bucket(5) == 'Thu'
        # Fri(6), Sat(7), Sun(1) all collapse into one bucket.
        assert day_bucket(6) == day_bucket(7) == day_bucket(1) == 'Fri-Sun'
        assert day_bucket(None) == '__nodow__'


# ==================== even weekly distribution end-to-end ====================

class TestEvenWeeklyDistribution:
    def _data(self):
        # 5 containers each on Mon(2), Tue(3), Wed(4), Thu(5), Fri(6) — 25 total.
        rows = []
        for dow in (2, 3, 4, 5, 6):
            for i in range(5):
                rows.append({'Dray SCAC(FL)': 'ZZZZ', 'Discharged Port': 'TIW',
                             'Category': 'TL', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                             'Day of Week': dow, 'Facility': 'OLM1',
                             'Container Numbers': f'D{dow}C{i:05d}', 'Container Count': 1,
                             'Base Rate': 100, 'Total Rate': 100})
        return pd.DataFrame(rows)

    def test_allocation_spread_across_days(self):
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                'Port': 'TIW', 'Maximum Container Count': 10})
        con, unc, *_ = apply_constraints_to_data(self._data(), c)
        hjbt = con[con['Dray SCAC(FL)'] == 'HJBT']
        assert hjbt['Container Count'].sum() == 10
        per_bucket = hjbt.groupby(hjbt['Day of Week'].map(day_bucket))['Container Count'].sum()
        assert len(per_bucket) == 5, f"expected all 5 buckets, got {dict(per_bucket)}"
        assert per_bucket.max() <= 3, f"one day hogged volume: {dict(per_bucket)}"

    def test_weekend_collapses_into_one_bucket(self):
        # Volume only on Fri(6)/Sat(7)/Sun(1) — these are ONE bucket, so a target
        # smaller than the pool still draws from across the weekend days.
        rows = []
        for dow in (6, 7, 1):
            for i in range(4):
                rows.append({'Dray SCAC(FL)': 'ZZZZ', 'Discharged Port': 'TIW',
                             'Category': 'TL', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                             'Day of Week': dow, 'Facility': 'OLM1',
                             'Container Numbers': f'W{dow}C{i:05d}', 'Container Count': 1,
                             'Base Rate': 100, 'Total Rate': 100})
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                'Port': 'TIW', 'Maximum Container Count': 6})
        con, unc, *_ = apply_constraints_to_data(pd.DataFrame(rows), c)
        assert con[con['Dray SCAC(FL)'] == 'HJBT']['Container Count'].sum() == 6

    def test_target_met_even_when_one_day_is_thin(self):
        rows = [{'Dray SCAC(FL)': 'ZZZZ', 'Discharged Port': 'TIW', 'Category': 'TL',
                 'Lane': 'USTIWOLM1', 'Week Number': 27, 'Day of Week': 2,
                 'Facility': 'OLM1', 'Container Numbers': 'MON00001',
                 'Container Count': 1, 'Base Rate': 100, 'Total Rate': 100}]
        for dow in (3, 4, 5):
            for i in range(10):
                rows.append({'Dray SCAC(FL)': 'ZZZZ', 'Discharged Port': 'TIW',
                             'Category': 'TL', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                             'Day of Week': dow, 'Facility': 'OLM1',
                             'Container Numbers': f'D{dow}C{i:05d}', 'Container Count': 1,
                             'Base Rate': 100, 'Total Rate': 100})
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                'Port': 'TIW', 'Maximum Container Count': 12})
        con, unc, *_ = apply_constraints_to_data(pd.DataFrame(rows), c)
        assert con[con['Dray SCAC(FL)'] == 'HJBT']['Container Count'].sum() == 12

    def test_rows_without_day_still_allocate(self):
        # No Day of Week column at all — must still allocate the full target.
        rows = []
        for i in range(20):
            rows.append({'Dray SCAC(FL)': 'ZZZZ', 'Discharged Port': 'TIW',
                         'Category': 'TL', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                         'Facility': 'OLM1', 'Container Numbers': f'N{i:05d}',
                         'Container Count': 1, 'Base Rate': 100, 'Total Rate': 100})
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                'Port': 'TIW', 'Maximum Container Count': 8})
        con, unc, *_ = apply_constraints_to_data(pd.DataFrame(rows), c)
        assert con[con['Dray SCAC(FL)'] == 'HJBT']['Container Count'].sum() == 8

    def test_container_conservation(self):
        data = self._data()
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                'Port': 'TIW', 'Maximum Container Count': 10})
        con, unc, *_ = apply_constraints_to_data(data, c)
        tot_c = con['Container Count'].sum() if len(con) else 0
        tot_u = unc['Container Count'].sum() if len(unc) else 0
        assert tot_c + tot_u == data['Container Count'].sum()


# ==================== scope x (min / max / percent) ====================

class TestScopeWithMinMaxPercentCombinations:
    """Vessel / Terminal / Port scoping combined with Min / Max / Percent must be
    respected on BOTH the constrained and unconstrained tables."""

    def _data(self, per_vessel=60):
        rows = []
        for vessel, term in (('VES_A', 'T18'), ('VES_B', 'T30')):
            for i in range(per_vessel):
                rows.append({'Dray SCAC(FL)': 'HJBT', 'Discharged Port': 'TIW',
                             'Category': 'TL', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                             'Day of Week': (i % 5) + 2, 'Terminal': term, 'SSL': 'MAEU',
                             'Vessel': vessel, 'Facility': 'OLM1',
                             'Container Numbers': f'{vessel}{i:05d}', 'Container Count': 1,
                             'Base Rate': 100, 'Total Rate': 100})
            for i in range(10):
                rows.append({'Dray SCAC(FL)': 'RKNE', 'Discharged Port': 'TIW',
                             'Category': 'TL', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                             'Day of Week': (i % 5) + 2, 'Terminal': term, 'SSL': 'MAEU',
                             'Vessel': vessel, 'Facility': 'OLM1',
                             'Container Numbers': f'{vessel}ALT{i:05d}', 'Container Count': 1,
                             'Base Rate': 120, 'Total Rate': 120})
        return pd.DataFrame(rows)

    def _total(self, con, unc, **filt):
        def t(df):
            if not len(df):
                return 0
            m = pd.Series(True, index=df.index)
            for k, v in filt.items():
                if k not in df.columns:
                    return 0
                m &= df[k].astype(str) == str(v)
            return df[m]['Container Count'].sum()
        return t(con) + t(unc)

    def test_vessel_max_40_holds_both_tables(self):
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                'Vessel': 'VES_A', 'Maximum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(self._data(), c)
        total = self._total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Vessel': 'VES_A'})
        assert total <= 40, f"HJBT on VES_A = {total}, expected <= 40"

    def test_terminal_max_holds_both_tables(self):
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                'Terminal': 'T18', 'Maximum Container Count': 25})
        con, unc, *_ = apply_constraints_to_data(self._data(), c)
        total = self._total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Terminal': 'T18'})
        assert total <= 25, f"HJBT at T18 = {total}, expected <= 25"

    def test_port_percent_ceiling(self):
        # Percent denominator is the FULL in-scope pool at TIW: 120 HJBT + 20 RKNE
        # = 140. 30% of 140 = 42. Percent acts as a ceiling, so HJBT gets exactly 42.
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                'Percent Allocation': 30})
        con, unc, *_ = apply_constraints_to_data(self._data(), c)
        allocated = con[con['Dray SCAC(FL)'] == 'HJBT']['Container Count'].sum()
        assert allocated == 42, f"expected 42 (30% of 140), got {allocated}"

    def test_vessel_min_floor_respected(self):
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                'Vessel': 'VES_A', 'Minimum Container Count': 30})
        con, unc, *_ = apply_constraints_to_data(self._data(), c)
        allocated = con[(con['Dray SCAC(FL)'] == 'HJBT')
                        & (con['Vessel'] == 'VES_A')]['Container Count'].sum()
        assert allocated >= 30, f"min floor not met: {allocated}"

    def test_vessel_min_and_max_band(self):
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                'Vessel': 'VES_A', 'Minimum Container Count': 20,
                                'Maximum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(self._data(), c)
        allocated = con[(con['Dray SCAC(FL)'] == 'HJBT')
                        & (con['Vessel'] == 'VES_A')]['Container Count'].sum()
        assert 20 <= allocated <= 40, f"band violated: {allocated}"
        assert self._total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Vessel': 'VES_A'}) <= 40

    def test_terminal_and_vessel_combination(self):
        c1 = _make_constraint(**{'Priority Score': 2, 'Carrier': 'HJBT', 'Port': 'TIW',
                                 'Vessel': 'VES_A', 'Maximum Container Count': 40})
        c2 = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                 'Terminal': 'T30', 'Maximum Container Count': 15})
        cons = pd.concat([c1, c2], ignore_index=True)
        con, unc, *_ = apply_constraints_to_data(self._data(), cons)
        va = self._total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Vessel': 'VES_A'})
        t30 = self._total(con, unc, **{'Dray SCAC(FL)': 'HJBT', 'Terminal': 'T30'})
        assert va <= 40, f"VES_A cap violated: {va}"
        assert t30 <= 15, f"T30 cap violated: {t30}"

    def test_allocation_within_capped_vessel_is_spread_across_days(self):
        # 40 on VES_A should still spread across the 5 day buckets, not pile up.
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                'Vessel': 'VES_A', 'Maximum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(self._data(), c)
        hjbt = con[(con['Dray SCAC(FL)'] == 'HJBT') & (con['Vessel'] == 'VES_A')]
        per_bucket = hjbt.groupby(hjbt['Day of Week'].map(day_bucket))['Container Count'].sum()
        assert len(per_bucket) == 5, f"not spread: {dict(per_bucket)}"

    def test_container_conservation(self):
        data = self._data()
        c = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
                                'Vessel': 'VES_A', 'Maximum Container Count': 40})
        con, unc, *_ = apply_constraints_to_data(data, c)
        tot_c = con['Container Count'].sum() if len(con) else 0
        tot_u = unc['Container Count'].sum() if len(unc) else 0
        assert tot_c + tot_u == data['Container Count'].sum()
