"""Regression tests for parse_ocean_eta — the "1/1/1970" Ocean ETA bug.

Symptom the user reported: Ocean ETA cells showing 1/1/1970 (the Unix epoch).
Root cause: pd.to_datetime(x, errors='coerce') reads a bare NUMBER as
nanoseconds-since-1970, so an Excel date serial (e.g. 45658) and 0/blank
sentinels all collapse to ~1970-01-01 instead of the real date (or NaT).

parse_ocean_eta must:
  * keep real date strings/datetimes (both ISO and US format),
  * convert Excel day serials with the 1899-12-30 origin (45658 -> 2025-01-01),
  * map 0 / tiny sentinels / blanks / junk to NaT (dropped downstream, not 1970),
  * pass an already-datetime64 column through unchanged (never re-number it).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from components.core.utils import parse_ocean_eta


def _mdy(series):
    return [(f"{d.month}/{d.day}/{d.year}" if pd.notna(d) else "NaT") for d in series]


class TestNoEpochFromNumbers:
    def test_zero_becomes_nat_not_1970(self):
        out = parse_ocean_eta(pd.Series([0, 0.0, "0"], dtype=object))
        assert _mdy(out) == ["NaT", "NaT", "NaT"], "0 must be NaT, never 1/1/1970"

    def test_excel_serial_converts_to_real_date(self):
        # 45658 is Excel's serial for 2025-01-01 (origin 1899-12-30).
        out = parse_ocean_eta(pd.Series([45658, 45659, 45660.0], dtype=object))
        assert _mdy(out) == ["1/1/2025", "1/2/2025", "1/3/2025"]

    def test_pure_numeric_column_no_1970(self):
        # Whole column numeric (the case that first slipped through): no epoch dates.
        out = parse_ocean_eta(pd.Series([0, 45658], dtype=object))
        assert _mdy(out) == ["NaT", "1/1/2025"]
        assert not any(d.year == 1970 for d in out if pd.notna(d))


class TestRealDatesPreserved:
    def test_iso_strings(self):
        out = parse_ocean_eta(pd.Series(["2025-03-04", "2025-12-31"]))
        assert _mdy(out) == ["3/4/2025", "12/31/2025"]

    def test_us_format_strings(self):
        out = parse_ocean_eta(pd.Series(["3/4/2025", "1/15/2025"]))
        assert _mdy(out) == ["3/4/2025", "1/15/2025"]

    def test_mixed_iso_and_us_in_one_column(self):
        # format="mixed" parses each cell independently so neither format is lost.
        out = parse_ocean_eta(pd.Series(["2025-01-01", "3/4/2025"], dtype=object))
        assert _mdy(out) == ["1/1/2025", "3/4/2025"]

    def test_no_real_date_dropped_in_mixed_column(self):
        s = pd.Series(["2025-01-01", "3/4/2025", 45658, 0, "", np.nan, "junk", 45659.0],
                      dtype=object)
        assert _mdy(parse_ocean_eta(s)) == [
            "1/1/2025", "3/4/2025", "1/1/2025", "NaT", "NaT", "NaT", "NaT", "1/2/2025",
        ]


class TestDatetime64Passthrough:
    def test_already_parsed_column_unchanged(self):
        s = pd.to_datetime(pd.Series(["2025-05-01", None, "2025-06-15"]))
        out = parse_ocean_eta(s)
        assert out.equals(s), "datetime64 column must pass through identical"

    def test_datetime64_nat_not_turned_into_epoch(self):
        s = pd.to_datetime(pd.Series([None, "2025-07-04"]))
        out = parse_ocean_eta(s)
        assert pd.isna(out.iloc[0])  # NaT stays NaT, not a huge-negative -> 1970


class TestMissingAndEdges:
    def test_blanks_and_junk_are_nat(self):
        out = parse_ocean_eta(pd.Series(["", "   ", None, np.nan, "not a date"], dtype=object))
        assert all(pd.isna(d) for d in out)

    def test_empty_series(self):
        assert len(parse_ocean_eta(pd.Series([], dtype=object))) == 0

    def test_index_is_preserved(self):
        s = pd.Series(["2025-01-01", 45658], index=[7, 99], dtype=object)
        out = parse_ocean_eta(s)
        assert list(out.index) == [7, 99]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
