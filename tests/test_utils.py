"""
Tests for components/utils.py utility functions.

Covers: join_container_ids, get_grouping_columns, normalize_facility_code,
        safe_numeric, format_currency, format_percentage, format_number,
        filter_excluded_carrier_facility_rows
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

from components.utils import (
    join_container_ids,
    get_grouping_columns,
    normalize_facility_code,
    normalize_facility_series,
    safe_numeric,
    format_currency,
    format_percentage,
    format_number,
    filter_excluded_carrier_facility_rows,
)


# ==================== join_container_ids ====================

class TestJoinContainerIds:
    def test_normal_list(self):
        assert join_container_ids(['C001', 'C002', 'C003']) == 'C001, C002, C003'

    def test_empty_list(self):
        assert join_container_ids([]) == ''

    def test_single_item(self):
        assert join_container_ids(['C001']) == 'C001'

    def test_filters_falsy(self):
        result = join_container_ids(['C001', '', None, 'C002'])
        assert result == 'C001, C002'


# ==================== get_grouping_columns ====================

class TestGetGroupingColumns:
    def test_base_columns_present(self):
        df = pd.DataFrame(columns=['Discharged Port', 'Lane', 'Facility', 'Week Number'])
        result = get_grouping_columns(df)
        assert result == ['Discharged Port', 'Lane', 'Facility', 'Week Number']

    def test_missing_columns_excluded(self):
        df = pd.DataFrame(columns=['Lane', 'Week Number'])
        result = get_grouping_columns(df)
        assert result == ['Lane', 'Week Number']

    def test_category_inserted_first(self):
        df = pd.DataFrame(columns=['Category', 'Lane', 'Week Number'])
        result = get_grouping_columns(df)
        assert result[0] == 'Category'

    def test_ssl_inserted_after_category(self):
        df = pd.DataFrame(columns=['Category', 'SSL', 'Lane', 'Week Number'])
        result = get_grouping_columns(df)
        assert result.index('SSL') == 1

    def test_vessel_inserted(self):
        df = pd.DataFrame(columns=['Vessel', 'Lane', 'Week Number'])
        result = get_grouping_columns(df)
        assert 'Vessel' in result

    def test_terminal_appended(self):
        df = pd.DataFrame(columns=['Terminal', 'Lane', 'Week Number'])
        result = get_grouping_columns(df)
        assert result[-1] == 'Terminal'

    def test_custom_base_cols(self):
        df = pd.DataFrame(columns=['A', 'B', 'C'])
        result = get_grouping_columns(df, base_cols=['A', 'B'])
        assert result == ['A', 'B']

    def test_empty_data(self):
        df = pd.DataFrame()
        result = get_grouping_columns(df)
        assert result == []


# ==================== normalize_facility_code ====================

class TestNormalizeFacilityCode:
    def test_amazon_prefix(self):
        assert normalize_facility_code('Amazon REWR') == 'REWR'

    def test_regular_code(self):
        assert normalize_facility_code('HGR6-5') == 'HGR6'

    def test_short_code(self):
        assert normalize_facility_code('ABC') == 'ABC'

    def test_four_char(self):
        assert normalize_facility_code('IUSF') == 'IUSF'

    def test_nan(self):
        assert normalize_facility_code(np.nan) == ''

    def test_empty_string(self):
        assert normalize_facility_code('') == ''

    def test_case_insensitive_amazon(self):
        assert normalize_facility_code('amazon XYZ1') == 'XYZ1'

    def test_whitespace(self):
        assert normalize_facility_code('  IUSF-5  ') == 'IUSF'


# ==================== normalize_facility_series ====================

class TestNormalizeFacilitySeries:
    def test_mixed_series(self):
        s = pd.Series(['Amazon REWR', 'HGR6-5', 'IUSF'])
        result = normalize_facility_series(s)
        assert list(result) == ['REWR', 'HGR6', 'IUSF']


# ==================== safe_numeric ====================

class TestSafeNumeric:
    def test_int(self):
        assert safe_numeric(42) == 42.0

    def test_float(self):
        assert safe_numeric(3.14) == 3.14

    def test_nan(self):
        assert safe_numeric(np.nan) == 0.0

    def test_none(self):
        assert safe_numeric(None) == 0.0

    def test_currency_string(self):
        assert safe_numeric('$1,234.56') == 1234.56

    def test_percentage_string(self):
        assert safe_numeric('85.5%') == 85.5

    def test_invalid_string(self):
        assert safe_numeric('abc') == 0.0

    def test_plain_number_string(self):
        assert safe_numeric('100') == 100.0


# ==================== format_currency ====================

class TestFormatCurrency:
    def test_positive(self):
        assert format_currency(1234.56) == '$1,234.56'

    def test_zero(self):
        assert format_currency(0) == 'N/A'

    def test_nan(self):
        assert format_currency(np.nan) == 'N/A'

    def test_large_number(self):
        assert format_currency(1000000) == '$1,000,000.00'

    def test_negative(self):
        assert format_currency(-500.50) == '$-500.50'


# ==================== format_percentage ====================

class TestFormatPercentage:
    def test_half(self):
        assert format_percentage(0.5) == '50.0%'

    def test_full(self):
        assert format_percentage(1.0) == '100.0%'

    def test_zero(self):
        assert format_percentage(0) == '0.0%'

    def test_nan(self):
        assert format_percentage(np.nan) == 'N/A'


# ==================== format_number ====================

class TestFormatNumber:
    def test_no_decimals(self):
        assert format_number(1234) == '1,234'

    def test_with_decimals(self):
        assert format_number(1234.567, decimals=2) == '1,234.57'

    def test_nan(self):
        assert format_number(np.nan) == 'N/A'

    def test_zero(self):
        assert format_number(0) == '0'


# ==================== filter_excluded_carrier_facility_rows ====================

class TestFilterExcludedCarrierFacilityRows:
    @pytest.fixture
    def facility_data(self):
        return pd.DataFrame({
            'Dray SCAC(FL)': ['ABCD', 'ABCD', 'EFGH', 'IJKL'],
            'Facility': ['IUSF-5', 'HGR6-5', 'IUSF-5', 'IUSF-5'],
            'Container Count': [10, 20, 15, 5],
        })

    def test_no_exclusions(self, facility_data):
        result = filter_excluded_carrier_facility_rows(facility_data, {})
        assert len(result) == 4

    def test_exclude_carrier_at_facility(self, facility_data):
        exclusions = {'ABCD': {'IUSF'}}
        result = filter_excluded_carrier_facility_rows(facility_data, exclusions)
        # ABCD at IUSF should be removed, but ABCD at HGR6 and others remain
        assert len(result) == 3
        assert not ((result['Dray SCAC(FL)'] == 'ABCD') & (result['Facility'].str.startswith('IUSF'))).any()

    def test_other_carriers_unaffected(self, facility_data):
        exclusions = {'ABCD': {'IUSF'}}
        result = filter_excluded_carrier_facility_rows(facility_data, exclusions)
        assert len(result[result['Dray SCAC(FL)'] == 'EFGH']) == 1
        assert len(result[result['Dray SCAC(FL)'] == 'IJKL']) == 1

    def test_multiple_exclusions(self, facility_data):
        exclusions = {'ABCD': {'IUSF'}, 'EFGH': {'IUSF'}}
        result = filter_excluded_carrier_facility_rows(facility_data, exclusions)
        assert len(result) == 2

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=['Dray SCAC(FL)', 'Facility', 'Container Count'])
        result = filter_excluded_carrier_facility_rows(df, {'ABCD': {'IUSF'}})
        assert len(result) == 0

    def test_no_facility_column(self):
        df = pd.DataFrame({'Dray SCAC(FL)': ['ABCD'], 'Container Count': [10]})
        result = filter_excluded_carrier_facility_rows(df, {'ABCD': {'IUSF'}})
        assert len(result) == 1  # Returns unchanged — no Facility column
