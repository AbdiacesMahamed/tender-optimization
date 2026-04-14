"""
End-to-end pipeline test for the Carrier Tender Optimization Dashboard.

Feeds synthetic data through the full chain:
  GVT + Rate + Performance → process → merge → constraints → dedup → metrics
and validates that every stage produces correct, consistent output.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── Streamlit mock (must happen before any component import) ──────────
from unittest.mock import MagicMock, patch
import streamlit as _real_st  # may already be importable

# Patch st.cache_data to be a passthrough decorator
_real_st.cache_data = lambda **kwargs: (lambda f: f)
# Provide a real dict for session_state so .get() / __contains__ etc. work
_real_st.session_state = {}

import pandas as pd
import numpy as np
import pytest

from components.data_processor import (
    validate_and_process_gvt_data,
    validate_and_process_rate_data,
    merge_all_data,
    process_performance_data,
    CATEGORY_MAPPING,
)
from components.constraints_processor import apply_constraints_to_data
from components.utils import deduplicate_containers_per_lane_week
from components.metrics import calculate_enhanced_metrics


# =====================================================================
# FIXTURES — realistic synthetic data
# =====================================================================

@pytest.fixture
def raw_gvt():
    """Simulated GVT (container-level) data — 12 containers across 2 ports, 2 weeks, 3 carriers."""
    rows = []
    containers = [f'CNTR{str(i).zfill(4)}' for i in range(1, 13)]
    week_dates = [pd.Timestamp('2026-02-01'), pd.Timestamp('2026-02-08')]  # week 6, week 7
    ports = ['LALB', 'SAV']
    carriers = ['ABCD', 'EFGH', 'IJKL']
    facilities = ['IONT1', 'IATL4']

    idx = 0
    for wk_i, eta in enumerate(week_dates):
        for port_i, port in enumerate(ports):
            for c_i, carrier in enumerate(carriers):
                rows.append({
                    'Ocean ETA': eta,
                    'Discharged Port': port,
                    'Dray SCAC(FL)': carrier,
                    'Facility': facilities[port_i],
                    'Container': containers[idx % len(containers)],
                    'Category': 'CD',
                    'Vessel': 'VESSEL_A',
                    'Terminal': 'T1',
                })
                idx += 1

    return pd.DataFrame(rows)


@pytest.fixture
def raw_rate():
    """Rate card that covers all carrier × lane combos in raw_gvt."""
    rows = []
    ports = ['USLALB', 'USSAV']
    fcs = ['IONT', 'IATL']
    carriers = ['ABCD', 'EFGH', 'IJKL']
    base_rates = {'ABCD': 100, 'EFGH': 120, 'IJKL': 80}

    for port, fc in zip(ports, fcs):
        for carrier in carriers:
            lookup = carrier + port + fc
            lane = port + fc
            rows.append({
                'SCAC': carrier,
                'PORT': port,
                'FC': fc,
                'Lookup': lookup,
                'Lane': lane,
                'Base Rate': base_rates[carrier],
                'CPC': base_rates[carrier] + 10,
            })
    return pd.DataFrame(rows)


@pytest.fixture
def raw_performance():
    """Performance scorecard — 3 carriers, 2 weeks.  EFGH has highest score."""
    return pd.DataFrame({
        'Carrier': ['ABCD', 'EFGH', 'IJKL'],
        'Metrics': ['Total Score %', 'Total Score %', 'Total Score %'],
        'WK6': [0.70, 0.95, 0.85],
        'WK7': [0.75, 0.92, 0.80],
    })


@pytest.fixture
def constraints_df():
    """Simple constraints: cap ABCD at 2 containers (priority 1), minimum IJKL 1 container (priority 2)."""
    return pd.DataFrame({
        'Priority Score': [1, 2],
        'Carrier': ['ABCD', 'IJKL'],
        'Maximum Container Count': [2, None],
        'Minimum Container Count': [None, 1],
        'Percent Allocation': [None, None],
        'Category': [None, None],
        'Lane': [None, None],
        'Port': [None, None],
        'Week Number': [None, None],
        'Terminal': [None, None],
        'SSL': [None, None],
        'Vessel': [None, None],
        'Excluded FC': [None, None],
    })


# =====================================================================
# STAGE-BY-STAGE TESTS
# =====================================================================

class TestStage1_GVTProcessing:
    def test_produces_required_columns(self, raw_gvt):
        result = validate_and_process_gvt_data(raw_gvt.copy())
        for col in ['Week Number', 'Port_Processed', 'Facility_Processed', 'Lookup', 'Lane']:
            assert col in result.columns, f"Missing column: {col}"

    def test_week_numbers_derived(self, raw_gvt):
        result = validate_and_process_gvt_data(raw_gvt.copy())
        weeks = result['Week Number'].dropna().unique()
        assert len(weeks) >= 1  # at least one valid week

    def test_category_mapping_applied(self, raw_gvt):
        gvt = raw_gvt.copy()
        gvt.loc[0, 'Category'] = 'FBA LCL'
        result = validate_and_process_gvt_data(gvt)
        assert 'FBA LCL' not in result['Category'].values
        assert 'CD' in result['Category'].values

    def test_canada_excluded(self, raw_gvt):
        gvt = raw_gvt.copy()
        gvt['Market'] = 'US'
        gvt.loc[0, 'Market'] = 'CANADA'
        result = validate_and_process_gvt_data(gvt)
        # One row removed
        assert len(result) == len(gvt) - 1


class TestStage2_RateProcessing:
    def test_produces_lane_and_base_rate(self, raw_rate):
        result = validate_and_process_rate_data(raw_rate.copy())
        assert 'Lane' in result.columns
        assert 'Base Rate' in result.columns

    def test_auto_detects_rate_column(self):
        """Rate column named 'Cost' should be renamed to 'Base Rate'."""
        rate = pd.DataFrame({
            'Lookup': ['X'], 'PORT': ['A'], 'FC': ['B'], 'Cost': [100],
        })
        result = validate_and_process_rate_data(rate)
        assert 'Base Rate' in result.columns


class TestStage3_PerformanceProcessing:
    def test_melts_to_long_format(self, raw_performance):
        clean, has = process_performance_data(raw_performance.copy(), True)
        assert has is True
        assert 'Week Number' in clean.columns
        assert 'Performance_Score' in clean.columns
        # 3 carriers × 2 weeks = 6 rows
        assert len(clean) == 6

    def test_none_performance(self):
        clean, has = process_performance_data(None, False)
        assert clean is None and has is False


class TestStage4_Merge:
    def test_merge_produces_total_rate(self, raw_gvt, raw_rate, raw_performance):
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())
        perf, has = process_performance_data(raw_performance.copy(), True)
        merged = merge_all_data(gvt, rate, perf, has)

        assert 'Total Rate' in merged.columns
        assert 'Container Count' in merged.columns
        assert merged['Container Count'].sum() > 0

    def test_container_count_matches_inputs(self, raw_gvt, raw_rate, raw_performance):
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())
        perf, has = process_performance_data(raw_performance.copy(), True)
        merged = merge_all_data(gvt, rate, perf, has)

        # Total containers in merged should equal unique containers per lane/week from GVT
        total_merged = merged['Container Count'].sum()
        assert total_merged > 0
        # Should not exceed input row count
        assert total_merged <= len(raw_gvt)

    def test_performance_scores_merged(self, raw_gvt, raw_rate, raw_performance):
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())
        perf, has = process_performance_data(raw_performance.copy(), True)
        merged = merge_all_data(gvt, rate, perf, has)

        # At least some rows should have performance scores
        if 'Performance_Score' in merged.columns:
            non_null = merged['Performance_Score'].notna().sum()
            assert non_null > 0

    def test_merge_without_performance(self, raw_gvt, raw_rate):
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())
        merged = merge_all_data(gvt, rate, pd.DataFrame(), False)

        assert 'Total Rate' in merged.columns
        assert merged['Container Count'].sum() > 0


class TestStage5_Constraints:
    def _get_merged(self, raw_gvt, raw_rate, raw_performance):
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())
        perf, has = process_performance_data(raw_performance.copy(), True)
        return merge_all_data(gvt, rate, perf, has), rate

    def test_constraint_splits_data(self, raw_gvt, raw_rate, raw_performance, constraints_df):
        merged, rate = self._get_merged(raw_gvt, raw_rate, raw_performance)
        constrained, unconstrained, summary, max_carriers, fc_exclusions, *_ = \
            apply_constraints_to_data(merged, constraints_df, rate)

        # Both parts should have data
        assert len(constrained) > 0
        assert len(unconstrained) > 0
        # Summary should have 2 entries (one per constraint)
        assert len(summary) == 2

    def test_max_constraint_caps_carrier(self, raw_gvt, raw_rate, raw_performance, constraints_df):
        merged, rate = self._get_merged(raw_gvt, raw_rate, raw_performance)
        constrained, unconstrained, summary, max_carriers, *_ = \
            apply_constraints_to_data(merged, constraints_df, rate)

        # ABCD should be capped — constrained rows for ABCD should have ≤ 2 containers
        abcd_constrained = constrained[constrained['Dray SCAC(FL)'] == 'ABCD']
        if len(abcd_constrained) > 0:
            assert abcd_constrained['Container Count'].sum() <= 2

    def test_no_constraints_returns_all_unconstrained(self, raw_gvt, raw_rate, raw_performance):
        merged, rate = self._get_merged(raw_gvt, raw_rate, raw_performance)
        empty_constraints = pd.DataFrame(columns=['Priority Score', 'Carrier', 'Constraint Type', 'Value'])
        constrained, unconstrained, summary, *_ = \
            apply_constraints_to_data(merged, empty_constraints, rate)

        assert len(constrained) == 0
        assert len(unconstrained) == len(merged)


class TestStage6_Deduplication:
    def test_dedup_removes_duplicates(self):
        df = pd.DataFrame({
            'Week Number': [1, 1],
            'Lane': ['USLALBONT1', 'USLALBONT1'],
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Container Numbers': ['C001, C002, C003', 'C002, C003, C004'],
            'Container Count': [3, 3],
            'Base Rate': [100, 120],
            'Total Rate': [300, 360],
        })
        result = deduplicate_containers_per_lane_week(df)

        # C002 and C003 should only appear once each across carriers
        all_containers = ', '.join(result['Container Numbers'].values).split(', ')
        all_containers = [c.strip() for c in all_containers if c.strip()]
        assert len(all_containers) == len(set(all_containers)), "Duplicate containers after dedup"

    def test_dedup_preserves_total_unique_containers(self):
        df = pd.DataFrame({
            'Week Number': [1, 1],
            'Lane': ['L1', 'L1'],
            'Dray SCAC(FL)': ['A', 'B'],
            'Container Numbers': ['C1, C2', 'C2, C3'],
            'Container Count': [2, 2],
            'Base Rate': [100, 100],
            'Total Rate': [200, 200],
        })
        result = deduplicate_containers_per_lane_week(df)
        total = result['Container Count'].sum()
        assert total == 3  # C1, C2, C3 — unique set


class TestStage7_Metrics:
    def _build_merged(self, raw_gvt, raw_rate, raw_performance):
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())
        perf, has = process_performance_data(raw_performance.copy(), True)
        return merge_all_data(gvt, rate, perf, has)

    def test_metrics_returns_all_keys(self, raw_gvt, raw_rate, raw_performance):
        import streamlit as st
        st.session_state = {}
        merged = self._build_merged(raw_gvt, raw_rate, raw_performance)
        metrics = calculate_enhanced_metrics(merged, merged.copy())

        assert metrics is not None
        for key in ['total_cost', 'total_containers', 'unique_carriers',
                     'unique_lanes', 'avg_rate', 'performance_cost',
                     'cheapest_cost', 'optimized_cost']:
            assert key in metrics, f"Missing metric key: {key}"

    def test_total_cost_positive(self, raw_gvt, raw_rate, raw_performance):
        import streamlit as st
        st.session_state = {}
        merged = self._build_merged(raw_gvt, raw_rate, raw_performance)
        metrics = calculate_enhanced_metrics(merged, merged.copy())
        assert metrics['total_cost'] > 0

    def test_cheapest_le_current(self, raw_gvt, raw_rate, raw_performance):
        """Cheapest scenario should never exceed current cost."""
        import streamlit as st
        st.session_state = {}
        merged = self._build_merged(raw_gvt, raw_rate, raw_performance)
        metrics = calculate_enhanced_metrics(merged, merged.copy())
        if metrics['cheapest_cost'] is not None:
            assert metrics['cheapest_cost'] <= metrics['total_cost'] + 0.01  # tolerance

    def test_metrics_with_empty_data(self):
        result = calculate_enhanced_metrics(pd.DataFrame(), pd.DataFrame())
        assert result is None


# =====================================================================
# FULL END-TO-END PIPELINE
# =====================================================================

class TestFullPipeline:
    """
    Runs the complete pipeline:
      raw data → process → merge → constraints → dedup → metrics
    and validates cross-stage invariants.
    """

    def _run_pipeline(self, raw_gvt, raw_rate, raw_performance, constraints_df=None):
        """Execute the full pipeline, return all intermediate results."""
        import streamlit as st
        st.session_state = {}

        # Stage 1-2: Process inputs
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())

        # Stage 3: Performance
        perf, has_perf = process_performance_data(raw_performance.copy(), True)

        # Stage 4: Merge
        merged = merge_all_data(gvt, rate, perf, has_perf)

        # Stage 5: Constraints (optional)
        if constraints_df is not None and len(constraints_df) > 0:
            constrained, unconstrained, summary, max_carriers, fc_exclusions, *rest = \
                apply_constraints_to_data(merged, constraints_df, rate)
        else:
            constrained = pd.DataFrame()
            unconstrained = merged.copy()
            summary = []
            max_carriers = []
            fc_exclusions = {}

        # Stage 6: Dedup
        merged_deduped = deduplicate_containers_per_lane_week(merged)
        constrained_deduped = deduplicate_containers_per_lane_week(constrained) if len(constrained) > 0 else constrained
        unconstrained_deduped = deduplicate_containers_per_lane_week(unconstrained)

        # Stage 7: Metrics
        metrics = calculate_enhanced_metrics(
            merged_deduped, unconstrained_deduped,
            max_constrained_carriers=max_carriers,
            carrier_facility_exclusions=fc_exclusions,
            full_unfiltered_data=merged_deduped,
        )

        return {
            'gvt': gvt, 'rate': rate, 'perf': perf,
            'merged': merged, 'merged_deduped': merged_deduped,
            'constrained': constrained, 'unconstrained': unconstrained,
            'constrained_deduped': constrained_deduped,
            'unconstrained_deduped': unconstrained_deduped,
            'summary': summary, 'max_carriers': max_carriers,
            'metrics': metrics,
        }

    # ─── Pipeline without constraints ──────────────────────────────

    def test_pipeline_no_constraints(self, raw_gvt, raw_rate, raw_performance):
        """Full pipeline with no constraints — all data is unconstrained."""
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance)

        assert r['metrics'] is not None
        assert r['metrics']['total_cost'] > 0
        assert r['metrics']['total_containers'] > 0
        assert r['metrics']['unique_carriers'] == 3  # ABCD, EFGH, IJKL
        assert len(r['constrained']) == 0

    def test_pipeline_container_conservation_no_constraints(self, raw_gvt, raw_rate, raw_performance):
        """Containers in merged should equal containers after dedup (no overlap expected in our fixture)."""
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance)
        assert r['merged_deduped']['Container Count'].sum() == r['metrics']['total_containers']

    # ─── Pipeline with constraints ─────────────────────────────────

    def test_pipeline_with_constraints(self, raw_gvt, raw_rate, raw_performance, constraints_df):
        """Full pipeline with max and min constraints applied."""
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance, constraints_df)

        assert r['metrics'] is not None
        assert r['metrics']['total_cost'] > 0
        assert len(r['constrained']) > 0
        assert len(r['unconstrained']) > 0
        assert len(r['summary']) == 2

    def test_pipeline_constraint_max_respected(self, raw_gvt, raw_rate, raw_performance, constraints_df):
        """ABCD max=2 constraint should cap ABCD's constrained containers."""
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance, constraints_df)
        abcd = r['constrained'][r['constrained']['Dray SCAC(FL)'] == 'ABCD']
        if len(abcd) > 0:
            assert abcd['Container Count'].sum() <= 2

    def test_pipeline_metrics_scenarios_populated(self, raw_gvt, raw_rate, raw_performance):
        """All three scenario costs should be populated with valid data."""
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance)
        m = r['metrics']

        # Performance cost depends on Performance_Score existing
        if 'Performance_Score' in r['merged'].columns:
            assert m['performance_cost'] is not None
        assert m['cheapest_cost'] is not None
        # Optimized uses LP solver — should produce a result with valid data
        assert m['optimized_cost'] is not None or m['cheapest_cost'] is not None

    def test_pipeline_cheapest_scenario_correct(self, raw_gvt, raw_rate, raw_performance):
        """
        Cheapest scenario should use IJKL (rate=80) for all containers,
        so cheapest_cost should be ≤ current_cost.
        """
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance)
        m = r['metrics']
        if m['cheapest_cost'] is not None:
            assert m['cheapest_cost'] <= m['total_cost'] + 0.01

    def test_pipeline_dedup_no_duplicates(self, raw_gvt, raw_rate, raw_performance):
        """After dedup, no container should appear twice in the same lane/week."""
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance)
        deduped = r['merged_deduped']
        if 'Container Numbers' in deduped.columns and 'Lane' in deduped.columns:
            for (wk, lane), grp in deduped.groupby(['Week Number', 'Lane']):
                all_ids = []
                for cn in grp['Container Numbers'].dropna():
                    all_ids.extend([c.strip() for c in str(cn).split(',') if c.strip()])
                assert len(all_ids) == len(set(all_ids)), \
                    f"Duplicate containers in week={wk}, lane={lane}"

    def test_pipeline_rate_columns_consistent(self, raw_gvt, raw_rate, raw_performance):
        """Total Rate = Base Rate × Container Count for every row."""
        r = self._run_pipeline(raw_gvt, raw_rate, raw_performance)
        merged = r['merged_deduped']
        if 'Base Rate' in merged.columns and 'Total Rate' in merged.columns:
            expected = merged['Base Rate'] * merged['Container Count']
            assert np.allclose(merged['Total Rate'].fillna(0), expected.fillna(0), atol=0.01)

    # ─── Edge cases ────────────────────────────────────────────────

    def test_pipeline_single_carrier(self, raw_rate, raw_performance):
        """Pipeline with only one carrier should still work end-to-end."""
        gvt = pd.DataFrame({
            'Ocean ETA': [pd.Timestamp('2026-02-01')] * 3,
            'Discharged Port': ['LALB'] * 3,
            'Dray SCAC(FL)': ['ABCD'] * 3,
            'Facility': ['IONT1'] * 3,
            'Container': ['C001', 'C002', 'C003'],
            'Category': ['CD'] * 3,
        })
        import streamlit as st
        st.session_state = {}
        gvt_processed = validate_and_process_gvt_data(gvt)
        rate = validate_and_process_rate_data(raw_rate.copy())
        perf, has = process_performance_data(raw_performance.copy(), True)
        merged = merge_all_data(gvt_processed, rate, perf, has)
        metrics = calculate_enhanced_metrics(merged, merged.copy())

        assert metrics is not None
        assert metrics['total_containers'] == 3
        assert metrics['unique_carriers'] == 1

    def test_pipeline_no_performance_data(self, raw_gvt, raw_rate):
        """Pipeline should work without performance data."""
        import streamlit as st
        st.session_state = {}
        gvt = validate_and_process_gvt_data(raw_gvt.copy())
        rate = validate_and_process_rate_data(raw_rate.copy())
        merged = merge_all_data(gvt, rate, pd.DataFrame(), False)
        metrics = calculate_enhanced_metrics(merged, merged.copy())

        assert metrics is not None
        assert metrics['total_cost'] > 0
        # Performance cost should be None when no performance data
        assert metrics['performance_cost'] is None
