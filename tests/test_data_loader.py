"""
Tests for components/data_loader.py — focused on _transform_dray_master_format.

Regression coverage for the port-alias normalization fix (commit ac78138):
USBWI → USBAL, USEWR → USNYC, USORF → USNFK so rate Lookups match GVT.
"""
import pandas as pd
import pytest

# Streamlit is stubbed centrally in tests/conftest.py before any first-party import.

from components.data.loader import _transform_dray_master_format


@pytest.fixture
def dray_master_df():
    return pd.DataFrame({
        'SCAC': ['ABCD', 'EFGH', 'IJKL', 'MNOP'],
        'Port': ['USBWI', 'USEWR', 'USORF', 'USLAX'],
        'FC': ['IUSF', 'HGR6', 'REWR', 'ABC4'],
        'Base Rate': [100.0, 200.0, 150.0, 300.0],
        'Fuel Surcharge': [10.0, 20.0, 15.0, 30.0],
    })


class TestTransformDrayMaster:
    def test_port_aliases_normalized(self, dray_master_df):
        """USBWI→USBAL, USEWR→USNYC, USORF→USNFK."""
        result = _transform_dray_master_format(dray_master_df)
        ports = list(result['Port'])
        assert 'USBWI' not in ports
        assert 'USEWR' not in ports
        assert 'USORF' not in ports
        assert 'USBAL' in ports
        assert 'USNYC' in ports
        assert 'USNFK' in ports

    def test_non_aliased_port_unchanged(self, dray_master_df):
        result = _transform_dray_master_format(dray_master_df)
        assert 'USLAX' in list(result['Port'])

    def test_lookup_uses_normalized_port(self, dray_master_df):
        """The whole point of the alias: Lookup must match GVT's port code."""
        result = _transform_dray_master_format(dray_master_df)
        # Row 0 was USBWI → should produce SCAC + USBAL + FC
        row0 = result.iloc[0]
        assert row0['Lookup'] == 'ABCDUSBALIUSF'

    def test_cpc_is_base_plus_fuel(self, dray_master_df):
        result = _transform_dray_master_format(dray_master_df)
        for _, row in result.iterrows():
            assert row['CPC'] == row['Base Rate'] + dray_master_df.loc[
                dray_master_df['SCAC'] == row['SCAC'], 'Fuel Surcharge'
            ].iloc[0]

    def test_cpc_skipped_when_no_fuel_column(self):
        df = pd.DataFrame({
            'SCAC': ['ABCD'],
            'Port': ['USLAX'],
            'FC': ['IUSF'],
            'Base Rate': [100.0],
        })
        result = _transform_dray_master_format(df)
        assert 'CPC' not in result.columns

    def test_drops_rows_missing_essential_data(self):
        df = pd.DataFrame({
            'SCAC': ['ABCD', None],
            'Port': ['USLAX', 'USLAX'],
            'FC': ['IUSF', 'IUSF'],
            'Base Rate': [100.0, 200.0],
        })
        result = _transform_dray_master_format(df)
        assert len(result) == 1

    def test_does_not_mutate_input(self, dray_master_df):
        original_ports = list(dray_master_df['Port'])
        _transform_dray_master_format(dray_master_df)
        assert list(dray_master_df['Port']) == original_ports
