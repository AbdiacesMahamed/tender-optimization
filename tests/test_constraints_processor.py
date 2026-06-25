"""
Tests for components/constraints_processor.py.

Covers: allocate_specific_containers, process_constraints_file, apply_constraints_to_data
"""
import pandas as pd
import numpy as np
import pytest

# Streamlit is stubbed centrally in tests/conftest.py before any first-party import.

from components.constraints.processor import (
    allocate_specific_containers,
    apply_constraints_to_data,
    build_scope_filters,
    diagnose_no_match,
)


# ==================== FIXTURES ====================

@pytest.fixture
def sample_data():
    """Sample comprehensive data for constraint testing."""
    return pd.DataFrame({
        'Category': ['CD', 'CD', 'CD', 'TL', 'TL'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'ABCD', 'EFGH', 'IJKL'],
        'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USBALREWR', 'USLAXIUSF', 'USBALREWR'],
        'Discharged Port': ['LAX', 'LAX', 'BAL', 'LAX', 'BAL'],
        'Week Number': [9, 9, 9, 9, 10],
        'Facility': ['IUSF-5', 'IUSF-5', 'Amazon REWR', 'IUSF-5', 'Amazon REWR'],
        'Container Numbers': ['C001, C002, C003', 'C004, C005', 'C006, C007', 'C008, C009', 'C010'],
        'Container Count': [3, 2, 2, 2, 1],
        'Base Rate': [100, 200, 150, 200, 180],
        'Total Rate': [300, 400, 300, 400, 180],
    })


@pytest.fixture
def max_constraint():
    """Simple maximum container count constraint."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['ABCD'],
        'Maximum Container Count': [2],
        'Minimum Container Count': [None],
        'Percent Allocation': [None],
        'Category': [None],
        'Lane': [None],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': [None],
    })


@pytest.fixture
def scoped_max_constraint():
    """Maximum constraint scoped to a specific category and lane."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['ABCD'],
        'Maximum Container Count': [1],
        'Minimum Container Count': [None],
        'Percent Allocation': [None],
        'Category': ['CD'],
        'Lane': ['USLAXIUSF'],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': [None],
    })


@pytest.fixture
def percent_constraint():
    """Percent allocation constraint."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['EFGH'],
        'Maximum Container Count': [None],
        'Minimum Container Count': [None],
        'Percent Allocation': [50],  # 50%
        'Category': [None],
        'Lane': [None],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': [None],
    })


@pytest.fixture
def excluded_fc_constraint():
    """Excluded facility constraint."""
    return pd.DataFrame({
        'Priority Score': [10],
        'Carrier': ['ABCD'],
        'Maximum Container Count': [None],
        'Minimum Container Count': [None],
        'Percent Allocation': [None],
        'Category': [None],
        'Lane': [None],
        'Port': [None],
        'Week Number': [None],
        'Terminal': [None],
        'SSL': [None],
        'Vessel': [None],
        'Excluded FC': ['IUSF'],
    })


# ==================== allocate_specific_containers ====================

class TestAllocateSpecificContainers:
    def test_allocate_subset(self):
        row = pd.Series({'Container Numbers': 'C001, C002, C003'})
        tracker = {}
        allocated, remaining = allocate_specific_containers(row, 2, tracker, 'ABCD', 9)
        assert len(allocated) == 2
        assert len(remaining) == 1
        assert 'C001' in tracker
        assert 'C002' in tracker

    def test_allocate_all(self):
        row = pd.Series({'Container Numbers': 'C001, C002'})
        tracker = {}
        allocated, remaining = allocate_specific_containers(row, 5, tracker, 'ABCD', 9)
        assert len(allocated) == 2
        assert len(remaining) == 0

    def test_skip_already_allocated(self):
        row = pd.Series({'Container Numbers': 'C001, C002, C003'})
        tracker = {'C001': {'carrier': 'EFGH', 'week': 9, 'row_idx': None}}
        allocated, remaining = allocate_specific_containers(row, 2, tracker, 'ABCD', 9)
        assert 'C001' not in allocated
        assert len(allocated) == 2  # C002 and C003

    def test_empty_container_string(self):
        row = pd.Series({'Container Numbers': ''})
        tracker = {}
        allocated, remaining = allocate_specific_containers(row, 2, tracker, 'ABCD', 9)
        assert len(allocated) == 0
        assert len(remaining) == 0

    def test_tracker_records_metadata(self):
        row = pd.Series({'Container Numbers': 'C001'})
        tracker = {}
        allocate_specific_containers(row, 1, tracker, 'ABCD', 9)
        assert tracker['C001']['carrier'] == 'ABCD'
        assert tracker['C001']['week'] == 9


# ==================== apply_constraints_to_data ====================

class TestApplyConstraintsToData:
    def test_no_constraints(self, sample_data):
        constrained, unconstrained, summary, max_carriers, exclusions, logs = \
            apply_constraints_to_data(sample_data, None)
        assert len(constrained) == 0
        assert len(unconstrained) == len(sample_data)

    def test_max_constraint_allocates_correct_count(self, sample_data, max_constraint):
        constrained, unconstrained, summary, max_carriers, exclusions, logs = \
            apply_constraints_to_data(sample_data, max_constraint)
        assert constrained['Container Count'].sum() == 2
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'ABCD'

    def test_max_constraint_adds_to_exclusion_list(self, sample_data, max_constraint):
        _, _, _, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, max_constraint)
        assert len(max_carriers) == 1
        assert max_carriers[0]['carrier'] == 'ABCD'

    def test_max_constraint_scope_stored(self, sample_data, scoped_max_constraint):
        _, _, _, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, scoped_max_constraint)
        assert max_carriers[0]['category'] == 'CD'
        assert max_carriers[0]['lane'] == 'USLAXIUSF'
        assert max_carriers[0]['week'] is None  # wildcard

    def test_containers_preserved_after_constraints(self, sample_data, max_constraint):
        original_total = sample_data['Container Count'].sum()
        constrained, unconstrained, _, _, _, _ = \
            apply_constraints_to_data(sample_data, max_constraint)
        after_total = constrained['Container Count'].sum() + unconstrained['Container Count'].sum()
        assert after_total == original_total

    def test_percent_allocation(self, sample_data, percent_constraint):
        constrained, unconstrained, summary, _, _, _ = \
            apply_constraints_to_data(sample_data, percent_constraint)
        total = sample_data['Container Count'].sum()
        assert constrained['Container Count'].sum() >= 1
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'EFGH'

    def test_excluded_fc_creates_exclusion_dict(self, sample_data, excluded_fc_constraint):
        _, _, _, _, exclusions, _ = \
            apply_constraints_to_data(sample_data, excluded_fc_constraint)
        assert 'ABCD' in exclusions
        assert 'IUSF' in exclusions['ABCD']

    def test_multiple_constraints_priority_order(self, sample_data):
        constraints = pd.DataFrame({
            'Priority Score': [10, 5],
            'Carrier': ['ABCD', 'EFGH'],
            'Maximum Container Count': [2, 1],
            'Minimum Container Count': [None, None],
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
        constrained, _, summary, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, constraints)
        # Higher priority constraint (10) processed first
        assert summary[0]['priority'] == 10

    def test_empty_constraints_df(self, sample_data):
        empty_constraints = pd.DataFrame()
        constrained, unconstrained, _, _, _, _ = \
            apply_constraints_to_data(sample_data, empty_constraints)
        assert len(constrained) == 0
        assert len(unconstrained) == len(sample_data)

    def test_minimum_constraint(self, sample_data):
        constraints = pd.DataFrame({
            'Priority Score': [10],
            'Carrier': ['EFGH'],
            'Maximum Container Count': [None],
            'Minimum Container Count': [3],
            'Percent Allocation': [None],
            'Category': [None],
            'Lane': [None],
            'Port': [None],
            'Week Number': [None],
            'Terminal': [None],
            'SSL': [None],
            'Vessel': [None],
            'Excluded FC': [None],
        })
        constrained, _, summary, _, _, _ = \
            apply_constraints_to_data(sample_data, constraints)
        assert constrained['Container Count'].sum() == 3
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'EFGH'


class TestCarrierCaseInsensitiveMatching:
    """A constraint Carrier typed in any case should resolve to the data's spelling,
    so both the assignment write and the optimizer-exclusion match line up."""

    def _constraint(self, carrier):
        return pd.DataFrame({
            'Priority Score': [10],
            'Carrier': [carrier],
            'Maximum Container Count': [2],
            'Minimum Container Count': [None],
            'Percent Allocation': [None],
            'Category': [None], 'Lane': [None], 'Port': [None], 'Week Number': [None],
            'Terminal': [None], 'SSL': [None], 'Vessel': [None], 'Excluded FC': [None],
        })

    def test_lowercase_carrier_resolves_to_data_spelling(self, sample_data):
        # Data carries 'ABCD'; constraint typed 'abcd' must still allocate and assign 'ABCD'.
        constrained, _, _, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, self._constraint('abcd'))
        assert constrained['Container Count'].sum() == 2
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'ABCD'
        # Exclusion list uses the data's spelling so cascading_logic matches the real carrier.
        assert max_carriers[0]['carrier'] == 'ABCD'

    def test_mixed_case_carrier_resolves(self, sample_data):
        constrained, _, _, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, self._constraint('AbCd'))
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'ABCD'
        assert max_carriers[0]['carrier'] == 'ABCD'

    def test_unknown_carrier_passed_through_verbatim(self, sample_data):
        # A carrier not present in the data isn't remapped — Carrier is the assignment
        # target, not a filter, so it still allocates and is assigned exactly as typed.
        constrained, _, _, max_carriers, _, _ = \
            apply_constraints_to_data(sample_data, self._constraint('ZZZZ'))
        assert constrained['Dray SCAC(FL)'].iloc[0] == 'ZZZZ'
        assert max_carriers[0]['carrier'] == 'ZZZZ'

    def test_excluded_fc_carrier_case_insensitive(self, sample_data):
        constraint = pd.DataFrame({
            'Priority Score': [10],
            'Carrier': ['abcd'],
            'Maximum Container Count': [None], 'Minimum Container Count': [None],
            'Percent Allocation': [None], 'Category': [None], 'Lane': [None],
            'Port': [None], 'Week Number': [None], 'Terminal': [None],
            'SSL': [None], 'Vessel': [None], 'Excluded FC': ['IUSF'],
        })
        _, _, _, _, exclusions, _ = apply_constraints_to_data(sample_data, constraint)
        # Exclusion keyed by the data's spelling so it matches rows during reallocation.
        assert 'ABCD' in exclusions
        assert 'IUSF' in exclusions['ABCD']


class TestScopeDimensionNormalization:
    """Lane/Port/Terminal/SSL/Vessel scope filters match case- and whitespace-insensitively
    via build_scope_filters, so a constraint typed in any case still finds its rows."""

    def _scoped(self, **fields):
        base = {
            'Priority Score': 10, 'Carrier': 'ABCD',
            'Maximum Container Count': 5, 'Minimum Container Count': None,
            'Percent Allocation': None, 'Category': None, 'Lane': None,
            'Port': None, 'Week Number': None, 'Terminal': None,
            'SSL': None, 'Vessel': None, 'Excluded FC': None,
        }
        base.update(fields)
        return pd.DataFrame([base])

    def test_lane_short_code_lowercase(self, sample_data):
        # Data lane 'USLAXIUSF'; constraint short code 'iusf' (lowercase) must match.
        c, _, _, _, _, _ = apply_constraints_to_data(sample_data, self._scoped(Lane='iusf'))
        assert c['Container Count'].sum() > 0
        assert set(c['Lane'].str.upper().str[-4:]) == {'IUSF'}

    def test_lane_full_with_whitespace(self, sample_data):
        c, _, _, _, _, _ = apply_constraints_to_data(
            sample_data, self._scoped(Lane='  uslaxiusf '))
        assert c['Container Count'].sum() > 0

    def test_port_lowercase(self, sample_data):
        # Discharged Port 'LAX'; constraint 'lax' must match.
        c, _, _, _, _, _ = apply_constraints_to_data(sample_data, self._scoped(Port='lax'))
        assert c['Container Count'].sum() > 0
        assert set(c['Discharged Port'].unique()) == {'LAX'}

    def test_terminal_case_insensitive(self):
        data = pd.DataFrame({
            'Category': ['CD', 'CD'], 'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Lane': ['USLAXIUSF', 'USLAXIUSF'], 'Discharged Port': ['LAX', 'LAX'],
            'Week Number': [9, 9], 'Facility': ['IUSF-5', 'IUSF-5'],
            'Terminal': ['Pier T', 'Pier T'],
            'Container Numbers': ['C001, C002', 'C003'], 'Container Count': [2, 1],
            'Base Rate': [100, 200], 'Total Rate': [200, 200],
        })
        c, _, _, _, _, _ = apply_constraints_to_data(data, self._scoped(Terminal='pier t'))
        assert c['Container Count'].sum() > 0


class TestDayOfWeekConstraint:
    """Day of Week scope filter: data carries an Excel WEEKDAY number (Sun=1 … Sat=7);
    constraint accepts a number or a name and matches only that weekday's containers."""

    def _day_data(self):
        # Day of Week: 2=Mon, 3=Tue (Excel WEEKDAY). Same lane/week/carrier, different days.
        return pd.DataFrame({
            'Category': ['CD', 'CD', 'CD'],
            'Dray SCAC(FL)': ['ABCD', 'ABCD', 'ABCD'],
            'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USLAXIUSF'],
            'Discharged Port': ['LAX', 'LAX', 'LAX'],
            'Week Number': [9, 9, 9],
            'Day of Week': [2, 2, 3],
            'Facility': ['IUSF-5', 'IUSF-5', 'IUSF-5'],
            'Container Numbers': ['C001, C002', 'C003', 'C004, C005'],
            'Container Count': [2, 1, 2],
            'Base Rate': [100, 100, 100], 'Total Rate': [200, 100, 200],
        })

    def _constraint(self, day):
        # Parsed through process_constraints_file so day strings/numbers are normalized.
        from components.constraints.processor import process_constraints_file
        import io
        df = pd.DataFrame([{
            'Priority Score': 10, 'Carrier': 'WXYZ',
            'Maximum Container Count': 99, 'Day of Week': day,
        }])
        buf = io.BytesIO()
        df.to_excel(buf, index=False)
        buf.seek(0)
        return process_constraints_file(buf)

    def test_numeric_day_matches_only_that_weekday(self):
        # Day=2 (Monday) → only the 3 Monday containers (C001,C002,C003), not Tuesday's.
        constraints = self._constraint(2)
        c, _, _, _, _, _ = apply_constraints_to_data(self._day_data(), constraints)
        assert c['Container Count'].sum() == 3
        assert set(c['Day of Week'].unique()) == {2}

    def test_name_day_matches(self):
        # 'tue' → Excel 3 → only the 2 Tuesday containers.
        constraints = self._constraint('tue')
        c, _, _, _, _, _ = apply_constraints_to_data(self._day_data(), constraints)
        assert c['Container Count'].sum() == 2
        assert set(c['Day of Week'].unique()) == {3}

    def test_full_name_day_matches(self):
        constraints = self._constraint('Monday')
        c, _, _, _, _, _ = apply_constraints_to_data(self._day_data(), constraints)
        assert c['Container Count'].sum() == 3

    def test_day_appears_in_scope_and_exclusion(self):
        constraints = self._constraint('monday')
        _, _, summary, max_carriers, _, _ = \
            apply_constraints_to_data(self._day_data(), constraints)
        # Scope dict surfaces the parsed Excel day number.
        assert summary[0]['scope'].get('Day of Week') == 2
        # Max constraint registers the day for scoped optimizer exclusion.
        assert max_carriers[0]['day'] == 2


# ==================== constraint_summary diagnostics ====================

def _make_constraint(**fields):
    """Helper to build a single-row constraints DataFrame with overrides."""
    base = {
        'Priority Score': 10,
        'Carrier': None,
        'Maximum Container Count': None,
        'Minimum Container Count': None,
        'Percent Allocation': None,
        'Category': None,
        'Lane': None,
        'Port': None,
        'Week Number': None,
        'Terminal': None,
        'SSL': None,
        'Vessel': None,
        'Excluded FC': None,
    }
    base.update(fields)
    return pd.DataFrame([base])


class TestConstraintSummaryDiagnostics:
    """Each summary entry must carry eligible_containers, scope, reason."""

    REQUIRED_KEYS = {'priority', 'description', 'status', 'containers_allocated',
                     'eligible_containers', 'scope', 'reason'}

    def test_applied_entry_has_diagnostics(self, sample_data, max_constraint):
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, max_constraint)
        entry = summary[0]
        assert self.REQUIRED_KEYS.issubset(entry.keys())
        assert entry['status'] == 'Applied'
        # Eligible should reflect actual matching containers (ABCD has 5 across rows)
        assert entry['eligible_containers'] > 0
        assert entry['scope'].get('Target Carrier') == 'ABCD'

    def test_scope_captures_filter_values(self, sample_data, scoped_max_constraint):
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, scoped_max_constraint)
        entry = summary[0]
        assert entry['scope']['Category'] == 'CD'
        assert entry['scope']['Lane'] == 'USLAXIUSF'
        assert entry['scope']['Target Carrier'] == 'ABCD'

    def test_partial_status_explains_shortfall_from_pool(self, sample_data):
        # Request 100 containers but pool has only ~10
        constraints = _make_constraint(
            Carrier='EFGH',
            **{'Minimum Container Count': 100, 'Priority Score': 10},
        )
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'].startswith('Partial')
        assert entry['reason'] is not None
        assert 'matched this constraint' in entry['reason']
        assert entry['eligible_containers'] < 100

    def test_no_matching_data_explains_filter(self, sample_data):
        # Filter on a Lane that doesn't exist
        constraints = _make_constraint(
            Carrier='ABCD',
            Lane='USNOPE-NONE',
            **{'Maximum Container Count': 5},
        )
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        # Max constraint with no carrier match still continues to record carrier exclusion;
        # so accept either "Failed: No matching data" or "Applied" depending on path,
        # but the diagnostic keys must be present.
        assert self.REQUIRED_KEYS.issubset(entry.keys())
        assert entry['eligible_containers'] == 0
        assert entry['scope'].get('Lane') == 'USNOPE-NONE'

    def test_no_matching_data_no_max_carrier_returns_failed(self, sample_data):
        # Min/Percent constraint on impossible filter — gives "Failed: No matching data"
        constraints = _make_constraint(
            Carrier='ABCD',
            Lane='USNOPE-NONE',
            **{'Minimum Container Count': 5},
        )
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'] == 'Failed: No matching data'
        assert entry['reason'] is not None
        # Reason should pinpoint the offending filter, not give a generic message
        assert 'Lane=USNOPE-NONE' in entry['reason']
        assert entry['eligible_containers'] == 0

    def test_bucket_category_matches_normalized_data(self, sample_data):
        # Regression: data is normalized to the 'CD' bucket; a 'CD'-scoped rule
        # must match those rows (the inverse-mapping bug matched zero).
        constraints = _make_constraint(
            Carrier='ABCD', Category='CD',
            **{'Maximum Container Count': 3},
        )
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['eligible_containers'] > 0, "CD rule matched no CD rows"

    def test_raw_label_category_matches_normalized_bucket_data(self, sample_data):
        # Regression / both-directions: a constraint written with the RAW label
        # 'Retail CD' must still match data that was normalized to the 'CD' bucket.
        constraints = _make_constraint(
            Carrier='ABCD', Category='Retail CD',
            **{'Maximum Container Count': 3},
        )
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['eligible_containers'] > 0, "'Retail CD' rule matched no 'CD' rows"

    def test_no_match_combination_too_narrow_names_each_filter(self, sample_data):
        # Lane=USLAXIUSF matches rows in week 9 only; Week=10 matches the single
        # USBALREWR row. Each filter matches data on its own, but no single row
        # satisfies BOTH — the combination is too narrow.
        constraints = _make_constraint(
            Carrier='EFGH',
            Lane='USLAXIUSF',
            **{'Week Number': 10, 'Minimum Container Count': 1},
        )
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'] == 'Failed: No matching data'
        assert 'no single row satisfies all of them' in entry['reason']
        # Each dimension's standalone row count is surfaced
        assert 'Lane=USLAXIUSF' in entry['reason']
        assert 'Week=10' in entry['reason']

    def test_no_match_dead_filter_value_is_named(self, sample_data):
        # Week=99 exists nowhere; Lane is fine. Diagnosis must name the dead Week
        # filter (the actionable culprit), not the valid Lane.
        constraints = _make_constraint(
            Carrier='EFGH',
            Lane='USLAXIUSF',
            **{'Week Number': 99, 'Minimum Container Count': 1},
        )
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'] == 'Failed: No matching data'
        assert "isn't present in the GVT file" in entry['reason']
        assert 'Week=99' in entry['reason']
        # The valid Lane filter must NOT be blamed as dead
        assert 'Lane=USLAXIUSF' not in entry['reason']

    def test_excluded_fc_without_carrier_explains_error(self, sample_data):
        constraints = _make_constraint(
            **{'Excluded FC': 'IUSF', 'Maximum Container Count': 5},
        )
        # No Carrier set — the Excluded FC error fires first
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'] == 'Error: Excluded FC requires Carrier'
        assert entry['reason'] is not None
        assert 'Carrier' in entry['reason']

    def test_exclusion_only_constraint_explains_role(self, sample_data, excluded_fc_constraint):
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, excluded_fc_constraint)
        entry = summary[0]
        assert entry['status'] == 'Applied (Exclusion Rule)'
        assert entry['reason'] is not None
        assert 'blocked from' in entry['reason']
        assert entry['scope'].get('Excluded Facilities') == ['IUSF']

    def test_no_allocation_amount_explains_role(self, sample_data):
        # Constraint with Carrier but no Min/Max/Percent/Excluded FC → unactionable
        constraints = _make_constraint(Carrier='ABCD')
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'] == 'No allocation amount'
        assert entry['reason'] is not None
        assert "'Maximum'" in entry['reason'] or 'Minimum' in entry['reason']

    def test_eligible_containers_is_int(self, sample_data, max_constraint):
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, max_constraint)
        assert isinstance(summary[0]['eligible_containers'], int)


# ==================== cross-constraint attribution ====================

class TestClaimedByAttribution:
    """When a later constraint's pool was consumed by earlier ones, claimed_by names the priorities."""

    def test_higher_priority_consumes_pool_attribution(self, sample_data):
        """Priority 100 takes everything; Priority 50 with same scope reports who took it."""
        constraints = pd.DataFrame([
            {  # P100: take 100% of EFGH-eligible volume
                'Priority Score': 100, 'Carrier': 'EFGH',
                'Maximum Container Count': None, 'Minimum Container Count': None,
                'Percent Allocation': 100, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
            {  # P50: also wants EFGH volume but P100 already took it
                'Priority Score': 50, 'Carrier': 'EFGH',
                'Maximum Container Count': None, 'Minimum Container Count': 5,
                'Percent Allocation': None, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
        ])
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        # P100 processed first
        assert summary[0]['priority'] == 100
        # P50 should report claimed_by P100
        p50 = next(s for s in summary if s['priority'] == 50)
        assert p50['claimed_by'] is not None
        assert 100 in p50['claimed_by']
        assert p50['claimed_by'][100] > 0
        assert p50['reason'] is not None
        assert 'Priority 100' in p50['reason']

    def test_no_self_attribution(self, sample_data, percent_constraint):
        """A constraint must not list itself as having claimed its own containers."""
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, percent_constraint)
        entry = summary[0]
        # claimed_by should be empty (no other constraints exist)
        assert not entry['claimed_by']

    def test_claimed_by_none_when_pool_was_just_too_small(self, sample_data):
        """If no other constraint touched the scope, claimed_by stays empty and reason cites pool size."""
        constraints = pd.DataFrame([{
            'Priority Score': 10, 'Carrier': 'IJKL',
            'Maximum Container Count': None, 'Minimum Container Count': 1000,
            'Percent Allocation': None, 'Category': None, 'Lane': None, 'Port': None,
            'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
            'Excluded FC': None,
        }])
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'].startswith('Partial')
        assert not entry['claimed_by']
        assert 'in the source data' in entry['reason']

    def test_no_matching_data_attributes_to_claiming_priorities(self, sample_data):
        """When scope had volume but it was all consumed, status is 'Failed: No matching data'
        and reason names the claiming priorities."""
        constraints = pd.DataFrame([
            {  # P100 takes ALL containers
                'Priority Score': 100, 'Carrier': 'ABCD',
                'Maximum Container Count': 999, 'Minimum Container Count': None,
                'Percent Allocation': None, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
            {  # P50 gets nothing but had matching scope
                'Priority Score': 50, 'Carrier': 'EFGH',
                'Maximum Container Count': None, 'Minimum Container Count': 1,
                'Percent Allocation': None, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
        ])
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        p50 = next(s for s in summary if s['priority'] == 50)
        # P50's eligible pool was emptied by P100
        assert p50['claimed_by'] is not None
        assert 100 in p50['claimed_by']
        assert 'Priority 100' in p50['reason']


# ==================== percent fallback against remainder ====================

class TestPercentFallback:
    """When higher-priority constraints consume part of the pool, percent uses the
    remainder as denominator and reports a shortfall against the original-pool target."""

    def test_no_overlap_no_shortfall(self, sample_data):
        """50% of full pool (10) -> 5 allocated, no shortfall."""
        constraints = pd.DataFrame([{
            'Priority Score': 10, 'Carrier': 'EFGH',
            'Maximum Container Count': None, 'Minimum Container Count': None,
            'Percent Allocation': 50, 'Category': None, 'Lane': None, 'Port': None,
            'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
            'Excluded FC': None,
        }])
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        entry = summary[0]
        assert entry['status'] == 'Applied'
        assert entry['containers_allocated'] == 5
        # No shortfall reason
        assert entry['reason'] is None or 'shortfall' not in (entry['reason'] or '').lower()

    def test_overlap_recomputes_against_remainder_with_shortfall(self, sample_data):
        """P100 takes 8 of 10; P50 wants 50% — recompute against remainder of 2,
        target=1, status=Partial with shortfall vs original target of 5."""
        constraints = pd.DataFrame([
            {  # P100 takes 8
                'Priority Score': 100, 'Carrier': 'ABCD',
                'Maximum Container Count': 8, 'Minimum Container Count': None,
                'Percent Allocation': None, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
            {  # P50 wants 50% of original pool
                'Priority Score': 50, 'Carrier': 'EFGH',
                'Maximum Container Count': None, 'Minimum Container Count': None,
                'Percent Allocation': 50, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
        ])
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        p50 = next(s for s in summary if s['priority'] == 50)
        # 50% of remainder (2) = 1, ceil. Allocated = 1.
        assert p50['containers_allocated'] == 1
        # Original target was 5; shortfall = 4
        assert p50['status'] == 'Partial (shortfall: 4)'
        # Reason names the consuming priority and explains the recomputation
        assert 'remainder' in p50['reason'].lower()
        assert 'Priority 100' in p50['reason']
        # Method string surfaces both denominators
        assert 'remainder' in p50['method']

    def test_no_shortfall_when_count_unchanged(self, sample_data):
        """If P100 takes 1 of 10, P50's 50% of remainder=9 still ceils to 5,
        matching the original-pool target of 5. No shortfall."""
        constraints = pd.DataFrame([
            {  # P100 takes 1
                'Priority Score': 100, 'Carrier': 'ABCD',
                'Maximum Container Count': 1, 'Minimum Container Count': None,
                'Percent Allocation': None, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
            {  # P50 wants 50%
                'Priority Score': 50, 'Carrier': 'EFGH',
                'Maximum Container Count': None, 'Minimum Container Count': None,
                'Percent Allocation': 50, 'Category': None, 'Lane': None, 'Port': None,
                'Week Number': None, 'Terminal': None, 'SSL': None, 'Vessel': None,
                'Excluded FC': None,
            },
        ])
        _, _, summary, _, _, _ = apply_constraints_to_data(sample_data, constraints)
        p50 = next(s for s in summary if s['priority'] == 50)
        # 50% of 10 = 5, 50% of 9 = 5 (ceil) → no count difference → no shortfall
        assert p50['containers_allocated'] == 5
        assert p50['status'] == 'Applied'


# ==================== no-match diagnosis helpers (adversarial) ====================

def _series(**fields):
    """Build a single constraint as a Series (what diagnose_no_match consumes)."""
    base = {k: None for k in (
        'Priority Score', 'Carrier', 'Maximum Container Count', 'Minimum Container Count',
        'Percent Allocation', 'Category', 'Lane', 'Port', 'Week Number',
        'Terminal', 'SSL', 'Vessel', 'Excluded FC')}
    base['Priority Score'] = 10
    base.update(fields)
    return pd.Series(base)


class TestDiagnoseNoMatch:
    """Direct, adversarial coverage of build_scope_filters / diagnose_no_match —
    the engine behind the improved 'why did this constraint match nothing?' reason."""

    @pytest.fixture
    def data(self):
        return pd.DataFrame({
            'Category': ['CD', 'CD', 'TL'],
            'Lane': ['USLAXIUSF', 'USLAXIUSF', 'USBALREWR'],
            'Discharged Port': ['LAX', 'LAX', 'BAL'],
            'Week Number': [9, 9, 10],
            'Container Numbers': ['C1', 'C2', 'C3'],
            'Container Count': [1, 1, 1],
        })

    def test_no_filters_returns_none(self, data):
        # Carrier is the target, not a filter — a carrier-only constraint has nothing to blame.
        kind, reason = diagnose_no_match(_series(Carrier='EFGH'), data)
        assert kind is None and reason is None

    def test_missing_column_filter_is_dropped(self, data):
        # A filter whose backing column is absent must not raise — it's silently skipped.
        no_port = data.drop(columns=['Discharged Port'])
        assert build_scope_filters(_series(Port='LAX'), no_port) == []
        kind, reason = diagnose_no_match(_series(Port='LAX'), no_port)
        assert kind is None and reason is None

    def test_empty_dataframe_flags_dead(self, data):
        kind, reason = diagnose_no_match(_series(Lane='USLAXIUSF'), data.iloc[0:0])
        assert kind == 'dead'
        assert 'Lane=USLAXIUSF' in reason

    def test_nan_in_data_does_not_crash(self, data):
        data = data.copy()
        data.loc[0, 'Category'] = np.nan
        kind, reason = diagnose_no_match(_series(Category='ZZZ'), data)
        assert kind == 'dead'

    def test_category_matches_normalized_bucket_in_both_directions(self, data):
        # Data is normalized to buckets ('CD'/'TL'). A constraint may carry the
        # bucket OR a raw label — both must match. 'TL' hits the TL row directly;
        # 'Retail Transload' canonicalizes to TL and hits the same row.
        for value in ('TL', 'Retail Transload', 'retail transload'):
            specs = build_scope_filters(_series(Category=value), data)
            cat_spec = next(s for s in specs if s['dimension'] == 'Category')
            assert int(cat_spec['mask'].sum()) == 1, f"{value!r} should match the TL row"

    def test_truly_absent_category_is_dead(self, data):
        # ROBOTICS is a real bucket, but no row in this data carries it.
        kind, reason = diagnose_no_match(_series(Category='ROBOTICS'), data)
        assert kind == 'dead'
        assert 'Category=ROBOTICS' in reason

    def test_float_week_matches_int_row(self, data):
        # Excel stores weeks as floats (9.0). It must match the int-9 rows, so the
        # failure is a too-narrow combination, NOT a dead week.
        kind, reason = diagnose_no_match(
            _series(Lane='USBALREWR', **{'Week Number': 9.0}), data)
        assert kind == 'combination'

    def test_combination_too_narrow_lists_per_filter_counts(self, data):
        kind, reason = diagnose_no_match(
            _series(Lane='USLAXIUSF', **{'Week Number': 10}), data)
        assert kind == 'combination'
        assert 'Lane=USLAXIUSF → 2 row(s)' in reason
        assert 'Week=10 → 1 row(s)' in reason

    def test_multiple_dead_filters_all_named(self, data):
        kind, reason = diagnose_no_match(
            _series(Category='NOPE', Lane='USXXXXXXX'), data)
        assert kind == 'dead'
        assert 'Category=NOPE' in reason
        assert 'Lane=USXXXXXXX' in reason

    def test_dead_filter_named_valid_filter_not_blamed(self, data):
        # Week 99 is dead; Lane USLAXIUSF is valid — only the dead one is named.
        kind, reason = diagnose_no_match(
            _series(Lane='USLAXIUSF', **{'Week Number': 99}), data)
        assert kind == 'dead'
        assert 'Week=99' in reason
        assert 'Lane=USLAXIUSF' not in reason

    def test_mask_index_aligns_with_data(self, data):
        # Masks are &='d into the eligibility mask, so they must share the data's index.
        data = data.copy()
        data.index = [100, 200, 300]
        specs = build_scope_filters(_series(**{'Week Number': 9}), data)
        assert list(specs[0]['mask'].index) == [100, 200, 300]
        assert int(specs[0]['mask'].sum()) == 2


class TestSummaryPortScopeFilter:
    """The Applied Constraints Summary must respect the active sidebar Port filter:
    constraints scoped to other ports are hidden, global ones always show."""

    def _summary(self):
        return [
            {'priority': 1, 'scope': {'Port': 'TIW'}, 'status': 'Applied', 'containers_allocated': 10},
            {'priority': 2, 'scope': {'Port': 'SAV'}, 'status': 'Skipped', 'containers_allocated': 0},
            {'priority': 3, 'scope': {'Category': 'CD'}, 'status': 'Applied', 'containers_allocated': 5},
            {'priority': 4, 'scope': {'Port': 'tiw '}, 'status': 'Applied', 'containers_allocated': 2},
            {'priority': 5, 'scope': {}, 'status': 'Applied', 'containers_allocated': 1},
        ]

    def _kept(self, ports):
        import streamlit as st
        from components.constraints.processor import _filter_summary_by_active_ports
        st.session_state['filter_ports'] = ports
        return [i['priority'] for i in _filter_summary_by_active_ports(self._summary())]

    def test_no_filter_keeps_all(self):
        assert self._kept([]) == [1, 2, 3, 4, 5]

    def test_single_port_hides_other_ports_keeps_global(self):
        # TIW filter: TIW (1) + case/space variant (4) + global Category (3) + empty scope (5).
        assert self._kept(['TIW']) == [1, 3, 4, 5]

    def test_other_port_hides_tiw(self):
        assert self._kept(['SAV']) == [2, 3, 5]

    def test_multi_port_filter(self):
        assert self._kept(['TIW', 'SAV']) == [1, 2, 3, 4, 5]


class TestScopedMaxCeilingVsBroaderRule:
    """A scoped Maximum (e.g. a vessel cap) must bind as a HARD ceiling against
    every other rule — including a broader, higher-priority Minimum on the same
    carrier — and the cap must hold on the UNCONSTRAINED table too, so the carrier
    can never end up over-cap after the scenario optimizer runs.

    Models the real PNW case: HJBT min-130 at a port + HJBT max-40 on one vessel.
    The min rule must not pull more than 40 of that vessel's containers onto HJBT,
    and any vessel volume left unconstrained must not stay on HJBT.
    """

    def _data(self):
        # One port (TIW), week 27. 6 containers on VESSEL_A (the capped vessel) +
        # 6 on VESSEL_B, all currently HJBT, plus an alternate carrier RKNE present
        # on the lane so stripped volume has somewhere to go.
        rows = []
        for i in range(6):
            rows.append({'Dray SCAC(FL)': 'HJBT', 'Discharged Port': 'TIW',
                         'Vessel': 'VESSEL_A', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                         'Category': 'TL', 'Facility': 'OLM1',
                         'Container Numbers': f'AAAU000000{i}', 'Container Count': 1,
                         'Base Rate': 100, 'Total Rate': 100})
        for i in range(6):
            rows.append({'Dray SCAC(FL)': 'HJBT', 'Discharged Port': 'TIW',
                         'Vessel': 'VESSEL_B', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                         'Category': 'TL', 'Facility': 'OLM1',
                         'Container Numbers': f'BBBU000000{i}', 'Container Count': 1,
                         'Base Rate': 100, 'Total Rate': 100})
        # Alternate carrier rows on the same lane (so RKNE is a known lane carrier).
        for i in range(2):
            rows.append({'Dray SCAC(FL)': 'RKNE', 'Discharged Port': 'TIW',
                         'Vessel': 'VESSEL_B', 'Lane': 'USTIWOLM1', 'Week Number': 27,
                         'Category': 'TL', 'Facility': 'OLM1',
                         'Container Numbers': f'RRRU000000{i}', 'Container Count': 1,
                         'Base Rate': 120, 'Total Rate': 120})
        return pd.DataFrame(rows)

    def _constraints(self):
        # Priority 1: HJBT min 8 at TIW/wk27 (broad). Priority 2: HJBT max 2 on VESSEL_A.
        c_min = _make_constraint(**{
            'Priority Score': 1, 'Carrier': 'HJBT', 'Port': 'TIW',
            'Week Number': 27, 'Minimum Container Count': 8})
        c_cap = _make_constraint(**{
            'Priority Score': 2, 'Carrier': 'HJBT', 'Port': 'TIW',
            'Week Number': 27, 'Vessel': 'VESSEL_A', 'Maximum Container Count': 2})
        return pd.concat([c_min, c_cap], ignore_index=True)

    def test_vessel_cap_holds_against_broader_min_in_constrained(self):
        data = self._data()
        con, unc, summary, maxc, *_ = apply_constraints_to_data(data, self._constraints())
        hjbt_vessel_a = con[(con['Dray SCAC(FL)'] == 'HJBT')
                            & (con['Vessel'] == 'VESSEL_A')]['Container Count'].sum()
        assert hjbt_vessel_a <= 2, f"vessel cap violated in constrained: {hjbt_vessel_a}"

    def test_capped_carrier_stripped_from_unconstrained_on_capped_vessel(self):
        data = self._data()
        con, unc, summary, maxc, *_ = apply_constraints_to_data(data, self._constraints())
        # No HJBT may remain on VESSEL_A in the unconstrained table beyond the cap —
        # those over-cap rows must have been moved off HJBT.
        if len(unc) and 'Vessel' in unc.columns:
            hjbt_va_unc = unc[(unc['Dray SCAC(FL)'] == 'HJBT')
                              & (unc['Vessel'] == 'VESSEL_A')]['Container Count'].sum()
            assert hjbt_va_unc == 0, f"over-cap HJBT left unconstrained on VESSEL_A: {hjbt_va_unc}"

    def test_total_vessel_a_hjbt_never_exceeds_cap(self):
        # Across BOTH tables, HJBT on VESSEL_A must be <= the cap of 2.
        data = self._data()
        con, unc, summary, maxc, *_ = apply_constraints_to_data(data, self._constraints())
        def va(df):
            if not len(df) or 'Vessel' not in df.columns:
                return 0
            return df[(df['Dray SCAC(FL)'] == 'HJBT')
                      & (df['Vessel'] == 'VESSEL_A')]['Container Count'].sum()
        assert va(con) + va(unc) <= 2

    def test_container_conservation(self):
        data = self._data()
        con, unc, summary, maxc, *_ = apply_constraints_to_data(data, self._constraints())
        tot_c = con['Container Count'].sum() if len(con) else 0
        tot_u = unc['Container Count'].sum() if len(unc) else 0
        assert tot_c + tot_u == data['Container Count'].sum()


class TestMaxCeilingHoldsForEveryScopeDimension:
    """A scoped Maximum must bind as a hard ceiling no matter WHICH dimension scopes
    it — Category, Lane, Port, Week, Terminal, SSL, or Vessel — because the cap pre-scan
    and the allocation loop share build_scope_filters (the single source of truth for
    scope matching). One broad min rule tries to over-fill the carrier; the scoped cap
    must still hold across BOTH the constrained and unconstrained tables.
    """

    SCOPES = [
        ("Category", "TL"),
        ("Lane", "USTIWOLM1"),
        ("Week Number", 27),
        ("Terminal", "T18"),
        ("SSL", "MAEU"),
        ("Vessel", "VES_A"),
    ]

    def _data(self):
        rows = []
        for i in range(10):
            rows.append({'Dray SCAC(FL)': 'HJBT', 'Discharged Port': 'TIW', 'Category': 'TL',
                         'Lane': 'USTIWOLM1', 'Week Number': 27, 'Terminal': 'T18', 'SSL': 'MAEU',
                         'Vessel': 'VES_A', 'Facility': 'OLM1',
                         'Container Numbers': f'A{i:07d}', 'Container Count': 1,
                         'Base Rate': 100, 'Total Rate': 100})
        # An alternate carrier on the lane so stripped volume can be reassigned.
        for i in range(5):
            rows.append({'Dray SCAC(FL)': 'RKNE', 'Discharged Port': 'TIW', 'Category': 'TL',
                         'Lane': 'USTIWOLM1', 'Week Number': 27, 'Terminal': 'T18', 'SSL': 'MAEU',
                         'Vessel': 'VES_A', 'Facility': 'OLM1',
                         'Container Numbers': f'R{i:07d}', 'Container Count': 1,
                         'Base Rate': 120, 'Total Rate': 120})
        return pd.DataFrame(rows)

    @pytest.mark.parametrize("col,val", SCOPES)
    def test_cap_holds_against_broad_min(self, col, val):
        cap = _make_constraint(**{'Priority Score': 2, 'Carrier': 'HJBT',
                                   'Maximum Container Count': 3})
        cap.at[0, col] = val
        # Broad min at the port pulls HJBT hard; the scoped cap of 3 must still win.
        c_min = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                    'Port': 'TIW', 'Minimum Container Count': 9})
        cons = pd.concat([c_min, cap], ignore_index=True)
        con, unc, summary, maxc, *_ = apply_constraints_to_data(self._data(), cons)

        def in_scope(df):
            if not len(df) or col not in df.columns:
                return 0
            return df[(df['Dray SCAC(FL)'] == 'HJBT')
                      & (df[col].astype(str) == str(val))]['Container Count'].sum()
        assert in_scope(con) + in_scope(unc) <= 3, f"cap violated for scope {col}={val}"

    def test_min_respected_when_no_conflicting_cap(self):
        c_min = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                    'Lane': 'USTIWOLM1', 'Minimum Container Count': 6})
        con, unc, *_ = apply_constraints_to_data(self._data(), c_min)
        assert con[con['Dray SCAC(FL)'] == 'HJBT']['Container Count'].sum() >= 6

    def test_percent_respected_per_dimension(self):
        c_pct = _make_constraint(**{'Priority Score': 1, 'Carrier': 'HJBT',
                                    'Category': 'TL', 'Percent Allocation': 40})
        con, unc, *_ = apply_constraints_to_data(self._data(), c_pct)
        # 40% of the 15-container TL pool = 6.
        assert con[con['Dray SCAC(FL)'] == 'HJBT']['Container Count'].sum() == 6
