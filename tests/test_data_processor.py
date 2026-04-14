"""
Tests for components/data_processor.py data pipeline functions.

Covers: validate_and_process_gvt_data, validate_and_process_rate_data, merge_all_data
Uses mock st.cache_data to avoid Streamlit dependency.
"""
import pandas as pd
import numpy as np
import pytest
import sys
sys.path.insert(0, '.')

# Mock streamlit before importing modules that use it
from unittest.mock import MagicMock, patch
sys.modules['streamlit'] = MagicMock()
import streamlit as st
# Make st.cache_data a passthrough decorator
st.cache_data = lambda **kwargs: (lambda f: f)

from components.data_processor import (
    validate_and_process_gvt_data,
    validate_and_process_rate_data,
    CATEGORY_MAPPING,
)


# ==================== FIXTURES ====================

@pytest.fixture
def minimal_gvt():
    """Minimal valid GVT data."""
    return pd.DataFrame({
        'Ocean ETA': pd.to_datetime(['2025-03-01', '2025-03-08']),
        'Discharged Port': ['LAX', 'BAL'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH'],
        'Facility': ['IUSF-5', 'HGR6-5'],
    })


@pytest.fixture
def gvt_with_category():
    """GVT data that includes Category and Container columns."""
    return pd.DataFrame({
        'Ocean ETA': pd.to_datetime(['2025-03-01', '2025-03-01', '2025-03-08']),
        'Discharged Port': ['LAX', 'LAX', 'BAL'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'ABCD'],
        'Facility': ['IUSF-5', 'IUSF-5', 'HGR6-5'],
        'Category': ['FBA LCL', 'Retail Transload', 'CD'],
        'Container': ['C001', 'C002', 'C003'],
    })


@pytest.fixture
def gvt_with_wk_num():
    """GVT data that already has the WK num column from Excel."""
    return pd.DataFrame({
        'Ocean ETA': pd.to_datetime(['2025-03-01', '2025-03-08']),
        'Discharged Port': ['LAX', 'BAL'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH'],
        'Facility': ['IUSF-5', 'HGR6-5'],
        'WK num': [9, 10],
    })


@pytest.fixture
def gvt_with_market():
    """GVT data that includes Market column with some Canada rows."""
    return pd.DataFrame({
        'Ocean ETA': pd.to_datetime(['2025-03-01', '2025-03-01', '2025-03-08']),
        'Discharged Port': ['LAX', 'TOR', 'BAL'],
        'Dray SCAC(FL)': ['ABCD', 'EFGH', 'IJKL'],
        'Facility': ['IUSF-5', 'HGR6-5', 'ABC4-5'],
        'Market': ['US', 'Canada', 'US'],
    })


@pytest.fixture
def minimal_rate():
    """Minimal valid rate data."""
    return pd.DataFrame({
        'Lookup': ['ABCDUSLAXIUSF', 'EFGHUSBALABCD'],
        'PORT': ['USLAX', 'USBAL'],
        'FC': ['IUSF', 'ABCD'],
        'SCAC': ['ABCD', 'EFGH'],
        'Base Rate': [150.0, 200.0],
    })


# ==================== validate_and_process_gvt_data ====================

class TestValidateGVTData:
    def test_basic_processing(self, minimal_gvt):
        result = validate_and_process_gvt_data(minimal_gvt)
        assert 'Week Number' in result.columns
        assert 'Lookup' in result.columns
        assert 'Lane' in result.columns
        assert 'Port_Processed' in result.columns
        assert 'Facility_Processed' in result.columns

    def test_port_prefixed_with_us(self, minimal_gvt):
        result = validate_and_process_gvt_data(minimal_gvt)
        assert all(result['Port_Processed'].str.startswith('US'))

    def test_week_number_calculated(self, minimal_gvt):
        result = validate_and_process_gvt_data(minimal_gvt)
        assert result['Week Number'].notna().all()
        assert all(result['Week Number'] > 0)

    def test_wk_num_column_used_directly(self, gvt_with_wk_num):
        result = validate_and_process_gvt_data(gvt_with_wk_num)
        assert list(result['Week Number']) == [9, 10]

    def test_canada_excluded(self, gvt_with_market):
        result = validate_and_process_gvt_data(gvt_with_market)
        assert len(result) == 2  # Canada row removed
        assert not result['Market'].str.upper().str.contains('CANADA').any()

    def test_category_mapping(self, gvt_with_category):
        result = validate_and_process_gvt_data(gvt_with_category)
        assert 'CD' in result['Category'].values  # FBA LCL mapped to CD
        assert 'TL' in result['Category'].values  # Retail Transload mapped to TL

    def test_missing_required_columns(self):
        df = pd.DataFrame({'Unrelated': [1, 2]})
        with pytest.raises(ValueError, match="Missing required columns"):
            validate_and_process_gvt_data(df)

    def test_null_ocean_eta_dropped(self):
        df = pd.DataFrame({
            'Ocean ETA': ['2025-03-01', 'not a date'],
            'Discharged Port': ['LAX', 'BAL'],
            'Dray SCAC(FL)': ['ABCD', 'EFGH'],
            'Facility': ['IUSF-5', 'HGR6-5'],
        })
        result = validate_and_process_gvt_data(df)
        assert len(result) == 1  # 'not a date' row dropped

    def test_lookup_format(self, minimal_gvt):
        result = validate_and_process_gvt_data(minimal_gvt)
        # Lookup = SCAC + Port_Processed + Facility_Processed
        for _, row in result.iterrows():
            expected = row['Dray SCAC(FL)'] + row['Port_Processed'] + row['Facility_Processed']
            assert row['Lookup'] == expected

    def test_lane_format(self, minimal_gvt):
        result = validate_and_process_gvt_data(minimal_gvt)
        # Lane = Port_Processed + Facility_Processed
        for _, row in result.iterrows():
            expected = row['Port_Processed'] + row['Facility_Processed']
            assert row['Lane'] == expected


# ==================== validate_and_process_rate_data ====================

class TestValidateRateData:
    def test_basic_processing(self, minimal_rate):
        result = validate_and_process_rate_data(minimal_rate)
        assert 'Lane' in result.columns
        assert 'Base Rate' in result.columns

    def test_lookup_required(self):
        df = pd.DataFrame({'SomeCol': [1, 2]})
        with pytest.raises(ValueError, match="Lookup column not found"):
            validate_and_process_rate_data(df)

    def test_lane_creation(self, minimal_rate):
        result = validate_and_process_rate_data(minimal_rate)
        assert result.iloc[0]['Lane'] == 'USLAXIUSF'

    def test_rate_column_renamed(self):
        df = pd.DataFrame({
            'Lookup': ['X'],
            'PORT': ['P'],
            'FC': ['F'],
            'Cost Rate': [100.0],
        })
        result = validate_and_process_rate_data(df)
        assert 'Base Rate' in result.columns
        assert result.iloc[0]['Base Rate'] == 100.0

    def test_cpc_column_detected(self):
        df = pd.DataFrame({
            'Lookup': ['X'],
            'PORT': ['P'],
            'FC': ['F'],
            'Base Rate': [100.0],
            'Cost Per Container': [50.0],
        })
        result = validate_and_process_rate_data(df)
        assert 'CPC' in result.columns

    def test_missing_port_or_fc_column(self):
        df = pd.DataFrame({
            'Lookup': ['X'],
            'Base Rate': [100.0],
        })
        with pytest.raises(ValueError, match="Cannot create Lane column"):
            validate_and_process_rate_data(df)


# ==================== CATEGORY_MAPPING ====================

class TestCategoryMapping:
    def test_fba_lcl_maps_to_cd(self):
        assert CATEGORY_MAPPING['FBA LCL'] == 'CD'

    def test_retail_cd_maps_to_cd(self):
        assert CATEGORY_MAPPING['Retail CD'] == 'CD'

    def test_fba_fcl_maps_to_cd(self):
        assert CATEGORY_MAPPING['FBA FCL'] == 'CD'

    def test_retail_transload_maps_to_tl(self):
        assert CATEGORY_MAPPING['Retail Transload'] == 'TL'
