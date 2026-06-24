"""
Adversarial test suite for the analysis code sandbox.

This is the security-critical surface added for open-ended analysis: it executes
MODEL-WRITTEN pandas in-process, in a process that holds Bedrock/AWS credentials
in its environment. These tests are deliberately HOSTILE — they try to break out
of the sandbox (import os, read os.environ, open files, reach the network, walk
__subclasses__, abuse str.format), exhaust resources (infinite loops, huge
outputs), and feed garbage — and assert the sandbox refuses or degrades safely
rather than leaking, crashing, or mutating the caller's data.

A failure here is a security regression, not just a bug. Run them in isolation:
    python -m pytest tests/test_code_sandbox.py -q
"""
import os

import pandas as pd
import pytest

from components.chatbot import code_sandbox as S
from components.chatbot.code_sandbox import (
    check_code,
    run_sandboxed_code,
    jsonify_result,
)
from components.chatbot import tools as T


# ==================== fixtures ====================

@pytest.fixture
def df():
    return pd.DataFrame({
        "Week Number": [9, 9, 10, 10],
        "Category": ["CD", "TL", "CD", "CD"],
        "Discharged Port": ["LAX", "LAX", "NYC", "NYC"],
        "Dray SCAC(FL)": ["ABCD", "XPDR", "ABCD", "EFGH"],
        "Lane": ["USLAXIUSF", "USLAXIUSF", "USNYCABE8", "USNYCABE8"],
        "Container Count": [10, 5, 20, 7],
        "Base Rate": [100.0, 200.0, 150.0, 80.0],
        "Total Rate": [1000.0, 1000.0, 3000.0, 560.0],
    })


def _run(df, code, **kw):
    return run_sandboxed_code(df, code, **kw)


# ==================== happy path (so the deny rules aren't vacuously passing) ====================

def test_basic_groupby_returns_dataframe(df):
    out = _run(df, "result = df.groupby('Dray SCAC(FL)')['Container Count'].sum().reset_index()")
    assert out["ok"] is True
    assert out["result"]["type"] == "dataframe"
    assert "Dray SCAC(FL)" in out["result"]["columns"]


def test_series_result(df):
    out = _run(df, "result = df.groupby('Category')['Container Count'].sum()")
    assert out["ok"] is True
    assert out["result"]["type"] == "series"
    assert out["result"]["length"] == 2


def test_scalar_result(df):
    out = _run(df, "result = int(df['Container Count'].sum())")
    assert out["ok"] is True
    assert out["result"]["type"] == "scalar"
    assert out["result"]["value"] == 42


def test_derived_column_pivot(df):
    code = (
        "df2 = df.copy()\n"
        "df2['cpc'] = df2['Total Rate'] / df2['Container Count']\n"
        "result = df2.pivot_table(index='Dray SCAC(FL)', values='cpc', aggfunc='mean')"
    )
    out = _run(df, code)
    assert out["ok"] is True
    assert out["result"]["type"] == "dataframe"


def test_safe_pd_constructor_available(df):
    out = _run(df, "result = pd.DataFrame({'a': [1, 2, 3]})")
    assert out["ok"] is True
    assert out["result"]["row_count"] == 3


# ==================== escape attempts: imports ====================

@pytest.mark.parametrize("code", [
    "import os\nresult = os.environ",
    "import sys\nresult = sys.modules",
    "from os import environ\nresult = environ",
    "import subprocess\nresult = 1",
    "__import__('os').system('echo pwned')\nresult = 1",
])
def test_imports_are_rejected(df, code):
    out = _run(df, code)
    assert out["ok"] is False
    # Either a static violation or a NameError for __import__ — both are refusals.
    assert "violations" in out or "error" in out


# ==================== escape attempts: dunder / subclass walk ====================

@pytest.mark.parametrize("code", [
    "result = ().__class__.__bases__[0].__subclasses__()",
    "result = (1).__class__.__mro__",
    "result = type(df).__init__.__globals__",
    "result = df.__class__.__init__.__globals__['__builtins__']",
])
def test_dunder_attribute_access_rejected(df, code):
    out = _run(df, code)
    assert out["ok"] is False
    assert out.get("violations"), f"expected static violation for: {code}"


def test_double_underscore_name_rejected(df):
    out = _run(df, "result = __builtins__")
    assert out["ok"] is False
    assert out.get("violations")


# ==================== escape attempts: str.format gadget ====================

def test_str_format_is_blocked(df):
    # "{0.__class__}".format(obj) reaches __class__ without an Attribute node on obj.
    out = _run(df, "result = '{0.__class__}'.format(df)")
    assert out["ok"] is False
    assert out.get("violations")


def test_format_map_is_blocked(df):
    out = _run(df, "result = '{x.__class__}'.format_map({'x': df})")
    assert out["ok"] is False
    assert out.get("violations")


# ==================== escape attempts: dangerous builtins by name ====================

@pytest.mark.parametrize("name_code", [
    "result = open('secret.txt')",
    "result = eval('1+1')",
    "result = exec('x=1')",
    "result = getattr(df, 'to_csv')",
    "result = globals()",
    "result = locals()",
    "result = vars()",
    "result = compile('1', '<s>', 'eval')",
    "result = input()",
])
def test_dangerous_builtins_rejected(df, name_code):
    out = _run(df, name_code)
    assert out["ok"] is False
    assert "violations" in out or "error" in out


def test_open_not_in_namespace_even_if_static_missed(df):
    # Belt-and-suspenders: 'open' is also absent from builtins, so a call NameErrors.
    ns = S._build_namespace(df.copy())
    assert "open" not in ns["__builtins__"]
    assert "__import__" not in ns["__builtins__"]
    assert "eval" not in ns["__builtins__"]


# ==================== credential / filesystem exfil (the real threat) ====================

def test_cannot_read_real_environ(df, monkeypatch):
    # Plant a fake secret the way bedrock_client loads one, and prove a snippet
    # cannot reach it. (os is not importable; os name is not in scope.)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "super-secret-token")
    out = _run(df, "import os\nresult = os.environ.get('AWS_BEARER_TOKEN_BEDROCK')")
    assert out["ok"] is False
    # The secret must not appear anywhere in the structured response.
    assert "super-secret-token" not in repr(out)


def test_pd_shim_has_no_file_readers(df):
    # pd.read_csv / read_pickle / eval are file/eval vectors — must be absent.
    for attr in ("read_csv", "read_pickle", "read_sql", "eval", "read_parquet"):
        out = _run(df, f"result = pd.{attr}")
        assert out["ok"] is False, f"pd.{attr} should not be reachable"


def test_dataframe_writers_cannot_touch_filesystem(df, tmp_path):
    # REGRESSION: an adversarial probe found df.to_csv('/path') wrote a file even
    # though it returned None (so it hit the no-result branch). The file write is
    # the escape — it must be blocked statically, before any execution.
    target = tmp_path / "exfil.csv"
    out = _run(df, f"result = df.to_csv(r'{target}')")
    assert out["ok"] is False
    assert out.get("violations"), "df.to_csv must be a static violation"
    assert not target.exists(), "SECURITY: snippet wrote a file to disk"


@pytest.mark.parametrize("writer", [
    "to_pickle", "to_excel", "to_json", "to_sql", "to_clipboard", "to_parquet",
    "to_hdf", "to_html",
])
def test_all_dataframe_writers_blocked(df, writer):
    out = _run(df, f"result = df.{writer}")
    assert out["ok"] is False
    assert out.get("violations")


@pytest.mark.parametrize("code", [
    "result = df.eval('Base_Rate * 2')",
    "result = df.query('Base Rate > 100')",
    "result = df.pipe(lambda x: x)",
])
def test_pandas_expression_engine_blocked(df, code):
    # df.eval / df.query run pandas' own expression engine (un-audited eval
    # surface); df.pipe hands control to an arbitrary callable. All blocked.
    out = _run(df, code)
    assert out["ok"] is False
    assert out.get("violations")


def test_safe_in_memory_converters_still_work(df):
    # The deny list must NOT break legitimate in-memory conversions.
    for conv in ("to_dict", "to_numpy", "to_records"):
        out = _run(df, f"result = df.head(1).{conv}()")
        assert out["ok"] is True, f"df.{conv}() should be allowed"


# ==================== resource exhaustion ====================

def test_infinite_loop_times_out(df):
    out = _run(df, "while True:\n    pass\nresult = 1", timeout_s=0.5)
    assert out["ok"] is False
    assert "timed out" in out["error"].lower()


def test_with_statement_rejected(df):
    # `with open(...)` is a common file-access shape; With nodes are denied outright.
    out = _run(df, "with open('x') as f:\n    result = f.read()")
    assert out["ok"] is False
    assert out.get("violations")


def test_huge_dataframe_result_is_capped(df):
    code = "result = pd.DataFrame({'a': range(100000)})"
    out = _run(df, code, max_rows=50)
    assert out["ok"] is True
    assert out["result"]["rows_returned"] <= 50
    assert out["result"]["rows_omitted"] > 0
    assert out["result"]["row_count"] == 100000


def test_max_cells_caps_wide_frame(df):
    # A frame whose rows*cols would blow the cell budget gets row-capped.
    code = "result = pd.DataFrame({c: range(1000) for c in ['a','b','c','d','e']})"
    out = _run(df, code, max_rows=2000, max_cells=100)
    assert out["ok"] is True
    assert out["result"]["rows_returned"] <= 100 // 5


def test_stdout_is_captured_and_truncated(df):
    out = _run(df, "print('x' * 50000)\nresult = 1")
    assert out["ok"] is True
    assert "truncated" in out.get("stdout", "")


# ==================== malformed / garbage input ====================

def test_no_result_assignment_reports_clearly(df):
    out = _run(df, "x = df.sum()")
    assert out["ok"] is False
    assert "result" in out["error"].lower()


def test_syntax_error_reported_not_raised(df):
    out = _run(df, "result = (df.groupby(")
    assert out["ok"] is False
    assert out.get("violations")
    assert any("syntax" in v.lower() for v in out["violations"])


def test_runtime_error_reported_not_raised(df):
    out = _run(df, "result = df['NoSuchColumn'].sum()")
    assert out["ok"] is False
    assert "error" in out
    # A KeyError message names the column; that's fine — it's the snippet's own error.
    assert "KeyError" in out["error"] or "NoSuchColumn" in out["error"]


def test_empty_and_blank_code(df):
    for code in ["", "   ", "\n\n"]:
        out = _run(df, code)
        assert out["ok"] is False


def test_non_string_code(df):
    for code in [None, 123, ["result = 1"], {"code": "x"}]:
        out = _run(df, code)
        assert out["ok"] is False


def test_no_data_loaded():
    out = _run(None, "result = 1")
    assert out["ok"] is False
    assert "no data" in out["error"].lower()
    out2 = _run(pd.DataFrame(), "result = 1")
    assert out2["ok"] is False


def test_oversized_code_rejected(df):
    out = _run(df, "result = 1\n" + ("# pad\n" * 5000))
    assert out["ok"] is False
    assert out.get("violations")
    assert any("too long" in v.lower() for v in out["violations"])


# ==================== read-only guarantee ====================

def test_snippet_cannot_mutate_callers_dataframe(df):
    before = df["Base Rate"].tolist()
    out = _run(df, "df['Base Rate'] = 0\nresult = df['Base Rate'].sum()")
    assert out["ok"] is True
    # The snippet saw a copy; the caller's frame is untouched.
    assert df["Base Rate"].tolist() == before
    assert df["Base Rate"].sum() != 0


def test_snippet_cannot_add_column_to_caller(df):
    out = _run(df, "df['hacked'] = 1\nresult = list(df.columns)")
    assert out["ok"] is True
    assert "hacked" not in df.columns


# ==================== serialization safety ====================

def test_nan_and_inf_serialize_to_none(df):
    out = _run(df, "result = float('nan')")
    assert out["ok"] is True
    assert out["result"]["value"] is None
    out2 = _run(df, "result = float('inf')")
    assert out2["result"]["value"] is None


def test_timestamp_series_serializes(df):
    code = (
        "s = pd.to_datetime(pd.Series(['2026-01-01', '2026-02-01']))\n"
        "result = s"
    )
    out = _run(df, code)
    assert out["ok"] is True
    assert out["result"]["type"] == "series"


def test_dict_result_serializes(df):
    out = _run(df, "result = {'total': int(df['Container Count'].sum()), 'rows': len(df)}")
    assert out["ok"] is True
    assert out["result"]["type"] == "dict"
    assert out["result"]["data"]["total"] == 42


def test_list_result_capped(df):
    out = _run(df, "result = list(range(1000))", max_rows=10)
    assert out["ok"] is True
    assert out["result"]["type"] == "list"
    assert len(out["result"]["data"]) == 10
    assert out["result"]["rows_omitted"] == 990


def test_jsonify_is_json_serializable(df):
    import json
    out = _run(df, "result = df.describe()")
    assert out["ok"] is True
    json.dumps(out)  # must not raise


# ==================== check_code unit-level ====================

def test_check_code_clean_snippet_passes():
    assert check_code("result = df['Base Rate'].mean()") == []


def test_check_code_dedups_repeated_violations():
    v = check_code("a = x.__class__\nb = y.__class__\nc = z.__class__")
    # One deduped message, not three.
    assert len([m for m in v if "__class__" in m]) == 1


# ==================== wrapper + executor plumbing ====================

def test_tools_run_analysis_blank_code(df):
    assert T.run_analysis(df, "")["ok"] is False
    assert T.run_analysis(df, None)["ok"] is False


def test_tools_run_analysis_clamps_max_rows(df):
    # Garbage max_rows must not crash; falls back to a sane default.
    out = T.run_analysis(df, "result = list(range(10))", max_rows="lots")
    assert out["ok"] is True


def test_tools_run_analysis_caps_max_rows_upper_bound(df):
    out = T.run_analysis(df, "result = list(range(5000))", max_rows=999999)
    # Cap is clamped to 2000; result reflects the clamp.
    assert out["ok"] is True
    assert len(out["result"]["data"]) <= 2000


def test_executor_dispatches_run_analysis_and_flags_errors(df):
    from components.chatbot.chat_ui import _make_tool_executor
    ex = _make_tool_executor(df, rate_data=None, rate_type="Base Rate")

    ok_result, is_err = ex("run_analysis", {"code": "result = int(df['Container Count'].sum())"})
    assert is_err is False
    assert ok_result["ok"] is True
    assert ok_result["result"]["value"] == 42

    bad_result, is_err = ex("run_analysis", {"code": "import os\nresult = 1"})
    assert is_err is True  # surfaced as an error turn so the model can retry
    assert bad_result["ok"] is False


# ==================== analysis-memory + serialization hardening ===========

def test_memory_nested_mutable_not_corrupted_across_turns(df):
    # A snippet mutating a value NESTED inside a recalled memory object must not
    # corrupt the stored object (regression: shallow copy leaked nested mutables).
    mem = {"grp": {"carriers": ["A", "B"], "n": 2},
           "lst": [pd.DataFrame({"x": [10]})]}
    out = run_sandboxed_code(df, "memory['grp']['carriers'].append('PWNED')\nresult=1",
                             memory=mem)
    assert out["ok"] is True
    assert mem["grp"]["carriers"] == ["A", "B"], "nested list in store was corrupted"
    run_sandboxed_code(df, "memory['lst'][0].iloc[0,0] = -7\nresult=1", memory=mem)
    assert int(mem["lst"][0].iloc[0, 0]) == 10, "nested DataFrame in store was corrupted"


def test_circular_result_does_not_raise(df):
    # A self-referential result must serialize to a clean dict, never RecursionError
    # (the sandbox's "never raises" contract).
    for code in ("d={}\nd['self']=d\nresult=d", "l=[]\nl.append(l)\nresult=l"):
        out = run_sandboxed_code(df, code)
        assert isinstance(out, dict)
        assert out.get("ok") is True  # serialized via the depth guard, not crashed


def test_circular_result_via_run_analysis_save_as(df):
    out = T.run_analysis(df, "d={}\nd['self']=d\nresult=d", save_as="circ")
    assert isinstance(out, dict) and out.get("ok") is True
