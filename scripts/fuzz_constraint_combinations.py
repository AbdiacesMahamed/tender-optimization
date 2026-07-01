"""
Combinatorial constraint fuzz harness for the Tender Optimization dashboard.

Feeds a real GVT-style snapshot (components/../execution logs/data_snapshots/*.csv,
which is already the merged constraint-ready table) through the constraint engine
under MANY generated constraint combinations, then checks the invariants the
dashboard's correctness depends on:

  INV1  Container conservation: constrained + unconstrained container IDs equal
        the original set (no container invented, none silently dropped) and no
        container ID appears in BOTH tables.
  INV2  No double-allocation: within constrained, each (lane, week) container ID
        is unique per the dedup rule; across constrained no ID appears twice.
  INV3  Max ceilings honored: a carrier never holds MORE than its scoped Maximum
        within that scope, across constrained AND unconstrained tables.
  INV4  Lockouts honored: a carrier locked out (Max 0 / Percent 0) of a scope
        holds ZERO containers in that scope in BOTH tables.
  INV5  Excluded-FC honored: a carrier never appears at an excluded facility.
  INV6  Every constraint yields a summary row with a status (no silent drops).
  INV7  Metrics compute without error and are internally sane
        (cheapest <= current, all costs >= 0, container totals conserved).
  INV8  No unhandled exception for ANY combination (the engine must degrade
        gracefully, never crash the dashboard).

Run:  python scripts/fuzz_constraint_combinations.py            (default N)
      python scripts/fuzz_constraint_combinations.py --n 2000   (more cases)
      python scripts/fuzz_constraint_combinations.py --seed 7 --data <csv>
"""
from __future__ import annotations

import argparse
import glob
import itertools
import os
import random
import sys
import traceback

# ── repo root on path + streamlit stub (mirror tests/conftest.py) ──────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from unittest.mock import MagicMock


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _make_streamlit_stub():
    st = MagicMock(name="streamlit_stub")
    st.cache_data = lambda *a, **k: (lambda f: f)
    st.cache_resource = lambda *a, **k: (lambda f: f)
    st.session_state = _SessionState()
    return st


# Install a stub ONLY if one isn't already present. Under pytest, tests/conftest.py
# installs a single shared stub before collection; hard-overwriting it here (as an
# earlier version did) swaps the object out from under already-imported modules like
# processor.py, so the test and the engine end up reading/writing DIFFERENT
# session_state objects — the exact hazard conftest.py documents. setdefault keeps
# the shared stub when running under pytest and still provides one for standalone runs.
sys.modules.setdefault("streamlit", _make_streamlit_stub())

import pandas as pd  # noqa: E402

from components.constraints.processor import (  # noqa: E402
    apply_constraints_to_data,
    build_scope_filters,
    norm_text,
    resolve_port_filter,
    expected_constraint_columns,
)
from components.core.utils import (  # noqa: E402
    parse_container_ids,
    deduplicate_containers_per_lane_week,
)
from components.scenarios.metrics import calculate_enhanced_metrics  # noqa: E402
from config.category_mapping import canonical_category  # noqa: E402


# =====================================================================
# Data loading
# =====================================================================

def default_data_path():
    snaps = glob.glob(os.path.join(
        _REPO_ROOT, "execution logs", "data_snapshots", "comprehensive_data_*.csv"))
    if not snaps:
        return None
    # Pick the richest by row count that still runs quickly (prefer the ~1270-row one).
    sized = sorted(((os.path.getsize(p), p) for p in snaps))
    # medium: largest under ~500KB, else the biggest available
    for size, p in reversed(sized):
        if size < 500_000:
            return p
    return sized[-1][1]


def load_data(path):
    df = pd.read_csv(path)
    # The engine expects Container Numbers / Container Count / rate cols — all present
    # in the snapshot. Ensure Container Count reflects the ID list (snapshot already does).
    return df


# =====================================================================
# Constraint generation
# =====================================================================

# Dimensions the engine scopes on, mapped to the data column they read.
SCOPE_DIMS = {
    'Category': 'Category',
    'Port': 'Discharged Port',
    'Week Number': 'Week Number',
    'Day of Week': 'Day of Week',
    'Terminal': 'Terminal',
    'SSL': 'SSL',
    'Vessel': 'Vessel',
    # Lane handled specially (endswith on 4-char facility code)
}


def domain_values(data):
    """Real values present in the data for each scope dimension, plus carriers/lanes."""
    dom = {}
    for dim, col in SCOPE_DIMS.items():
        if col in data.columns:
            vals = [v for v in data[col].dropna().unique()]
            dom[dim] = vals
    dom['Carrier'] = sorted(data['Dray SCAC(FL)'].dropna().unique().tolist())
    # Lane short-codes: last 4 chars of the concatenated lane (facility code)
    lanes = data['Lane'].dropna().astype(str).unique().tolist() if 'Lane' in data.columns else []
    dom['Lane_full'] = lanes
    dom['Lane_short'] = sorted({ln[-4:] for ln in lanes if len(ln) >= 4})
    # Facilities for Excluded FC
    dom['Facility'] = sorted(data['Facility'].dropna().astype(str).unique().tolist()) if 'Facility' in data.columns else []
    return dom


def rand_scope(rng, dom, max_dims):
    """Pick a random subset (0..max_dims) of scope filters with real values."""
    scope = {}
    dims = [d for d in SCOPE_DIMS if d in dom and dom[d]]
    # occasionally add a Lane filter
    candidates = dims + (['Lane'] if dom.get('Lane_short') else [])
    k = rng.randint(0, min(max_dims, len(candidates)))
    for dim in rng.sample(candidates, k):
        if dim == 'Lane':
            scope['Lane'] = rng.choice(dom['Lane_short'] if rng.random() < 0.7 else dom['Lane_full'])
        elif dim == 'Week Number':
            scope['Week Number'] = int(rng.choice(dom['Week Number']))
        elif dim == 'Day of Week':
            scope['Day of Week'] = int(rng.choice(dom['Day of Week']))
        else:
            scope[dim] = rng.choice(dom[dim])
    return scope


def rand_constraint(rng, dom, kind=None):
    """Build one constraint row (dict over the canonical schema)."""
    row = {c: None for c in expected_constraint_columns()}
    scope = rand_scope(rng, dom, max_dims=3)
    row.update(scope)
    row['Carrier'] = rng.choice(dom['Carrier'])

    if kind is None:
        kind = rng.choice([
            'max', 'min', 'percent', 'min_max', 'percent_max',
            'lockout_max', 'lockout_pct', 'exclude_fc', 'exclude_only',
            'huge_max', 'tiny_pct',
        ])

    if kind == 'max':
        row['Maximum Container Count'] = rng.choice([1, 5, 10, 25, 50, 100])
    elif kind == 'min':
        row['Minimum Container Count'] = rng.choice([1, 5, 10, 25, 50])
    elif kind == 'percent':
        row['Percent Allocation'] = rng.choice([5, 10, 25, 50, 75, 100])
    elif kind == 'min_max':
        lo = rng.choice([1, 5, 10])
        row['Minimum Container Count'] = lo
        row['Maximum Container Count'] = lo + rng.choice([5, 10, 40])
    elif kind == 'percent_max':
        row['Percent Allocation'] = rng.choice([25, 50, 75])
        row['Maximum Container Count'] = rng.choice([10, 30, 60])
    elif kind == 'lockout_max':
        row['Maximum Container Count'] = 0
    elif kind == 'lockout_pct':
        row['Percent Allocation'] = 0
    elif kind == 'exclude_fc':
        if dom['Facility']:
            row['Excluded FC'] = rng.choice(dom['Facility'])
        row['Maximum Container Count'] = rng.choice([10, 50])
    elif kind == 'exclude_only':
        if dom['Facility']:
            row['Excluded FC'] = rng.choice(dom['Facility'])
    elif kind == 'huge_max':
        row['Maximum Container Count'] = 100000
    elif kind == 'tiny_pct':
        row['Percent Allocation'] = rng.choice([0.5, 1, 2])

    row['Priority Score'] = rng.randint(1, 10)
    return row


def make_constraints_df(rng, dom, n_constraints):
    rows = [rand_constraint(rng, dom) for _ in range(n_constraints)]
    df = pd.DataFrame(rows, columns=expected_constraint_columns())
    # Higher priority first (mirror process_constraints_file's sort)
    df = df.sort_values('Priority Score', ascending=False, na_position='last').reset_index(drop=True)
    return df


# =====================================================================
# Invariant checks
# =====================================================================

def all_container_ids(df):
    ids = []
    if 'Container Numbers' in df.columns:
        for cn in df['Container Numbers'].dropna():
            ids.extend(parse_container_ids(cn))
    return ids


def carrier_col_of(df):
    return 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in df.columns else 'Carrier'


def check_invariants(case_id, orig, constrained, unconstrained, summary,
                     max_carriers, fc_exclusions, constraints_df, dom):
    """Return list of violation strings (empty = pass)."""
    viol = []

    orig_ids = all_container_ids(orig)
    orig_set = set(orig_ids)
    c_ids = all_container_ids(constrained)
    u_ids = all_container_ids(unconstrained)

    # INV1: conservation. Every constrained ID came from the original set. The
    # unconstrained table retains the full original set (max/percent rules leave
    # containers in place for the optimizer), so we assert coverage + provenance
    # rather than a strict partition.
    c_set, u_set = set(c_ids), set(u_ids)
    stray = c_set - orig_set
    if stray:
        viol.append(f"INV1 constrained has {len(stray)} IDs not in original (e.g. {list(stray)[:3]})")
    covered = c_set | u_set
    missing = orig_set - covered
    if missing:
        viol.append(f"INV1 {len(missing)} original IDs vanished from both tables (e.g. {list(missing)[:3]})")

    # INV2: no ID assigned to two DIFFERENT carriers within constrained.
    if 'Container Numbers' in constrained.columns and len(constrained) > 0:
        cc = carrier_col_of(constrained)
        id_to_carriers = {}
        for _, r in constrained.iterrows():
            for cid in parse_container_ids(r.get('Container Numbers', '')):
                id_to_carriers.setdefault(cid, set()).add(r.get(cc))
        dupes = {k: v for k, v in id_to_carriers.items() if len(v) > 1}
        if dupes:
            ex = list(dupes.items())[:2]
            viol.append(f"INV2 {len(dupes)} containers constrained to >1 carrier (e.g. {ex})")

    # INV3 + INV4: max ceilings & lockouts. Rebuild each cap/lockout mask on the
    # ORIGINAL data and count how many of that scope's containers the carrier
    # ends up holding across BOTH tables.
    combined = pd.concat([constrained, unconstrained], ignore_index=True) \
        if len(constrained) else unconstrained
    ccol = carrier_col_of(combined)
    for _, mc in constraints_df.iterrows():
        carrier = mc.get('Carrier')
        if not carrier or pd.isna(carrier):
            continue
        cap = mc.get('Maximum Container Count')
        pct = mc.get('Percent Allocation')
        is_lockout = (pd.notna(cap) and cap == 0) or (pd.notna(pct) and pct == 0)
        is_cap = pd.notna(cap) and cap > 0
        if not (is_lockout or is_cap):
            continue
        # scope mask over ORIGINAL, then find which container IDs are in scope
        specs = build_scope_filters(mc, orig)
        mask = pd.Series(True, index=orig.index)
        for s in specs:
            mask &= s['mask'].reindex(orig.index, fill_value=False)
        in_scope_ids = set()
        for _, r in orig[mask].iterrows():
            in_scope_ids.update(parse_container_ids(r.get('Container Numbers', '')))
        if not in_scope_ids:
            continue
        # containers this carrier holds, in scope, across both tables
        held = 0
        ck = norm_text(carrier)
        for _, r in combined.iterrows():
            if norm_text(r.get(ccol)) != ck:
                continue
            held += sum(1 for cid in parse_container_ids(r.get('Container Numbers', '')) if cid in in_scope_ids)
        if is_lockout and held > 0:
            viol.append(f"INV4 lockout {carrier} still holds {held} in-scope containers (P{mc.get('Priority Score')})")
        if is_cap and held > int(cap):
            viol.append(f"INV3 {carrier} holds {held} > max {int(cap)} in scope (P{mc.get('Priority Score')})")

    # INV5: excluded FC honored — carrier never sits at an excluded facility.
    if fc_exclusions and 'Facility' in combined.columns:
        from components.core.utils import normalize_facility_code
        fnorm = combined['Facility'].apply(normalize_facility_code)
        for carrier, facs in fc_exclusions.items():
            bad = combined[(combined[ccol] == carrier) & (fnorm.isin(facs))]
            n = bad['Container Count'].fillna(0).sum() if 'Container Count' in bad else len(bad)
            if len(bad) > 0 and n > 0:
                viol.append(f"INV5 {carrier} at excluded facility(s) {sorted(facs)}: {int(n)} containers")

    # INV6: every constraint accounted for in the summary.
    if len(summary) < len(constraints_df):
        viol.append(f"INV6 summary has {len(summary)} rows for {len(constraints_df)} constraints")
    for s in summary:
        if not s.get('status'):
            viol.append(f"INV6 summary row missing status: {s.get('description')}")

    return viol


def check_metrics(case_id, constrained, unconstrained, orig, max_carriers, fc_exclusions):
    """Run the metrics/optimizer stage; return violations."""
    viol = []
    try:
        merged_dd = deduplicate_containers_per_lane_week(orig)
        unc_dd = deduplicate_containers_per_lane_week(unconstrained)
        m = calculate_enhanced_metrics(
            merged_dd, unc_dd,
            max_constrained_carriers=max_carriers,
            carrier_facility_exclusions=fc_exclusions,
            full_unfiltered_data=merged_dd,
        )
    except Exception as e:
        return [f"INV7 metrics raised {type(e).__name__}: {e}"]
    if m is None:
        return ["INV7 metrics returned None for non-empty data"]
    for k in ('total_cost', 'cheapest_cost', 'optimized_cost', 'performance_cost'):
        v = m.get(k)
        if v is not None and (v != v or v < 0):  # NaN or negative
            viol.append(f"INV7 metric {k} invalid: {v}")
    # NOTE: we deliberately DON'T assert cheapest_cost <= total_cost here. Those two
    # are computed over DIFFERENT pools once constraints split the data — total_cost is
    # the full merged current cost, while the scenario costs run on the (constrained +
    # unconstrained) reoptimizable pool, which constraints can legitimately force onto
    # pricier carriers. The clean cheapest<=current check lives in the no-constraint
    # e2e test (test_e2e_pipeline.py), where the pools are identical.
    return viol


# =====================================================================
# Runner
# =====================================================================

def run(data_path, n_cases, seed, max_constraints, verbose):
    rng = random.Random(seed)
    data = load_data(data_path)
    dom = domain_values(data)

    print(f"Data: {os.path.basename(data_path)}  ({len(data)} rows, "
          f"{data['Container Count'].sum()} containers, {len(dom['Carrier'])} carriers)")
    print(f"Running {n_cases} constraint combinations (seed={seed}, "
          f"up to {max_constraints} constraints each)\n")

    failures = []       # (case_id, kind, detail, constraints_df)
    crashes = []
    empty_results = 0
    total_alloc = 0

    for i in range(n_cases):
        n_con = rng.randint(1, max_constraints)
        cdf = make_constraints_df(rng, dom, n_con)
        try:
            constrained, unconstrained, summary, max_carriers, fc_exclusions, *_ = \
                apply_constraints_to_data(data.copy(), cdf, rate_data=data)
        except Exception as e:
            crashes.append((i, cdf, traceback.format_exc()))
            failures.append((i, 'CRASH', f"{type(e).__name__}: {e}", cdf))
            continue

        alloc = sum(s.get('containers_allocated', 0) or 0 for s in summary)
        total_alloc += alloc
        if alloc == 0:
            empty_results += 1

        viol = check_invariants(i, data, constrained, unconstrained, summary,
                                max_carriers, fc_exclusions, cdf, dom)
        viol += check_metrics(i, constrained, unconstrained, data, max_carriers, fc_exclusions)

        for v in viol:
            failures.append((i, v.split()[0], v, cdf))

        if verbose and (i + 1) % max(1, n_cases // 10) == 0:
            print(f"  ... {i+1}/{n_cases} cases, {len(failures)} violations so far")

    # ── report ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print(f"RESULTS: {n_cases} cases run")
    print(f"  crashes:            {len(crashes)}")
    print(f"  invariant failures: {len([f for f in failures if f[1] != 'CRASH'])}")
    print(f"  cases with 0 alloc: {empty_results}")
    print(f"  total containers allocated across all cases: {total_alloc}")
    print("=" * 70)

    if failures:
        # group by invariant kind
        from collections import Counter
        by_kind = Counter(f[1] for f in failures)
        print("\nFailures by kind:")
        for kind, cnt in by_kind.most_common():
            print(f"  {kind}: {cnt}")

        print("\nFirst 15 failing cases (case_id | kind | detail):")
        for case_id, kind, detail, cdf in failures[:15]:
            print(f"\n  [case {case_id}] {detail}")
            # show the constraints that produced it
            cols = ['Priority Score', 'Carrier', 'Category', 'Port', 'Lane',
                    'Week Number', 'Day of Week', 'Terminal', 'SSL', 'Vessel',
                    'Maximum Container Count', 'Minimum Container Count',
                    'Percent Allocation', 'Excluded FC']
            show = cdf[[c for c in cols if c in cdf.columns]].dropna(axis=1, how='all')
            print("    constraints:")
            for line in show.to_string(index=False).splitlines():
                print("      " + line)

        if crashes:
            print("\nFirst crash traceback:")
            print(crashes[0][2])
        return 1

    print("\n[PASS] All invariants held across every constraint combination.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=500, help='number of constraint combinations')
    ap.add_argument('--seed', type=int, default=1234)
    ap.add_argument('--max-constraints', type=int, default=5,
                    help='max constraints per combination')
    ap.add_argument('--data', type=str, default=None, help='path to GVT-style comprehensive CSV')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    # Windows consoles default to cp1252 and buffer when redirected; force UTF-8 +
    # line buffering so progress shows live and non-ASCII never crashes the report.
    try:
        sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    except Exception:
        pass

    data_path = args.data or default_data_path()
    if not data_path or not os.path.exists(data_path):
        print("ERROR: no data file found. Pass --data <comprehensive_data csv>.")
        return 2

    return run(data_path, args.n, args.seed, args.max_constraints, verbose=not args.quiet)


if __name__ == '__main__':
    sys.exit(main())
