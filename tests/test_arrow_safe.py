"""Regression tests for arrow_safe — the mixed-type-column display crash.

Production incident: rendering the analysis table crashed the whole Streamlit
run with

    pyarrow.lib.ArrowTypeError: ("Expected bytes, got a 'int' object",
        'Conversion failed for column Carp Appointment with type object')

A passthrough GVT column (`Carp Appointment`) held mixed python types in one
`object` column — some cells int, some str/blank. pyarrow can't serialize that,
so st.dataframe raised, the script died, and the hosted health check reported
"connection reset by peer" on /healthz. arrow_safe coerces such columns to a
single (string) type so the frame always serializes.
"""
from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pytest

from components.core.utils import arrow_safe


def _to_arrow_ok(df: pd.DataFrame) -> bool:
    """True if the frame serializes to Arrow the way st.dataframe needs."""
    pa.Table.from_pandas(df)
    return True


def test_mixed_int_and_str_column_would_crash_then_is_fixed():
    # Reproduce the exact shape: an object column mixing int and str (+ blank).
    df = pd.DataFrame({
        "Carp Appointment": [1, "scheduled", 3, "", 5],
        "Container Count": [1, 2, 3, 4, 5],
    })
    # Sanity: the raw frame really does break Arrow (guards against the fixture
    # silently becoming serializable and making the test vacuous).
    with pytest.raises(Exception):
        pa.Table.from_pandas(df)

    safe = arrow_safe(df)
    assert _to_arrow_ok(safe)
    # The offending column is now all strings; ints render without ".0".
    assert list(safe["Carp Appointment"]) == ["1", "scheduled", "3", "", "5"]


def test_clean_numeric_column_is_left_untouched():
    df = pd.DataFrame({"Container Count": [1, 2, 3], "Rate": [10.5, 20.0, 30.25]})
    safe = arrow_safe(df)
    # No mixed-type columns -> same object back, dtypes preserved (still numeric).
    assert safe["Container Count"].dtype == df["Container Count"].dtype
    assert safe["Rate"].dtype == df["Rate"].dtype
    assert _to_arrow_ok(safe)


def test_clean_string_column_is_left_untouched():
    df = pd.DataFrame({"Carrier": ["RKNE", "HJBT", "ABCD"]})
    safe = arrow_safe(df)
    assert list(safe["Carrier"]) == ["RKNE", "HJBT", "ABCD"]
    assert _to_arrow_ok(safe)


def test_all_null_object_column_does_not_crash():
    df = pd.DataFrame({"Carp Appointment": [None, None], "x": [1, 2]})
    safe = arrow_safe(df)
    assert _to_arrow_ok(safe)


def test_float_with_text_coerces_integers_cleanly():
    # A numeric column that picked up a stray label: ints shouldn't show as "2.0".
    df = pd.DataFrame({"Appt": [2.0, 4.0, "TBD"]})
    safe = arrow_safe(df)
    assert list(safe["Appt"]) == ["2", "4", "TBD"]
    assert _to_arrow_ok(safe)


def test_none_and_empty_inputs_pass_through():
    assert arrow_safe(None) is None
    empty = pd.DataFrame()
    assert arrow_safe(empty) is empty


def test_does_not_mutate_input():
    df = pd.DataFrame({"Carp Appointment": [1, "x"]})
    before = df["Carp Appointment"].tolist()
    arrow_safe(df)
    assert df["Carp Appointment"].tolist() == before  # original untouched
