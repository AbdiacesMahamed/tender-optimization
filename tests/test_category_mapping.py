"""
Tests for config/category_mapping.py — the single source of truth for matching
a business Category value across spellings.

The bug this guards against: GVT data is normalized on load (Retail CD / FBA FCL
/ FBA LCL -> 'CD'), while constraint files / chatbot scopes may carry either the
raw label or the bucket code. Matching must canonicalize BOTH sides so the two
never cancel to zero (a 'CD' rule matching no 'CD' rows).
"""
import pandas as pd
import pytest

# Streamlit is stubbed centrally in tests/conftest.py before any first-party import.

from config.category_mapping import (
    canonical_category,
    category_matches,
    RAW_TO_CANONICAL,
)
from components.data.processor import CATEGORY_MAPPING


class TestCanonicalCategory:
    @pytest.mark.parametrize("value,expected", [
        ("CD", "CD"),
        ("Retail CD", "CD"),
        ("FBA FCL", "CD"),
        ("FBA LCL", "CD"),
        ("fba lcl", "CD"),          # case-insensitive
        ("  Retail CD  ", "CD"),    # whitespace-insensitive
        ("TL", "TL"),
        ("Retail Transload", "TL"),
        ("Robotics", "ROBOTICS"),
        ("Amazon Robotics", "ROBOTICS"),
        ("Devices", "DEVICES"),
        ("Amazon Devices", "DEVICES"),
        ("Imports", "IMPORTS"),     # unknown -> itself (upper/stripped)
    ])
    def test_folds_to_expected_bucket(self, value, expected):
        assert canonical_category(value) == expected

    @pytest.mark.parametrize("blank", [None, "", "   ", float("nan")])
    def test_blank_is_none(self, blank):
        assert canonical_category(blank) is None


class TestCategoryMatchesBothDirections:
    def test_bucket_constraint_matches_raw_label_data(self):
        # Constraint says 'CD'; a raw GVT label survived un-normalized in the data.
        assert category_matches("CD", "Retail CD")
        assert category_matches("CD", "FBA FCL")

    def test_raw_label_constraint_matches_bucket_data(self):
        # Constraint says 'Retail CD'; data already normalized to 'CD'.
        assert category_matches("Retail CD", "CD")

    def test_bucket_constraint_matches_bucket_data(self):
        # The common case: both sides already normalized.
        assert category_matches("CD", "CD")

    def test_different_buckets_do_not_match(self):
        assert not category_matches("CD", "TL")
        assert not category_matches("Retail Transload", "Retail CD")

    def test_unknown_category_matches_itself(self):
        assert category_matches("Imports", "imports")
        assert not category_matches("Imports", "Exports")


class TestNormalizationDriftGuard:
    """data/processor.CATEGORY_MAPPING normalizes the data; this module matches
    against it. If a raw label is added to one but not the other, a constraint
    scoped to that label would silently match zero rows. This test fails the
    moment the two drift apart."""

    def test_every_data_normalized_label_is_known_to_the_matcher(self):
        for raw_label, bucket in CATEGORY_MAPPING.items():
            # The matcher must fold the raw label to the same bucket the data
            # pipeline collapses it into.
            assert canonical_category(raw_label) == canonical_category(bucket), (
                f"data/processor maps {raw_label!r} -> {bucket!r}, but the matcher "
                f"folds them to {canonical_category(raw_label)!r} and "
                f"{canonical_category(bucket)!r}. Add {raw_label!r} to "
                f"config/category_mapping.RAW_TO_CANONICAL."
            )

    def test_raw_map_keys_are_upper_cased(self):
        # canonical_category upper-cases its input before lookup, so RAW_TO_CANONICAL
        # keys must be upper-case or they will never be hit.
        for key in RAW_TO_CANONICAL:
            assert key == key.upper(), f"{key!r} must be upper-case to be matched"
