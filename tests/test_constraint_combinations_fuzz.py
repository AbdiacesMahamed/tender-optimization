"""
Fast regression wrapper around scripts/fuzz_constraint_combinations.py.

The full harness fuzzes hundreds of constraint combinations against a large
real GVT snapshot; that's too slow for CI. Here we run a small, fixed-seed
batch against the smallest real snapshot and assert ZERO crashes and ZERO
invariant violations — locking in the two correctness fixes this harness found:

  * NaN-carrier leak into the over-cap/lockout re-home candidate set, which
    crashed sorted() (and could assign NaN as a carrier) for ANY max/lockout
    constraint when the GVT data had blank carriers on a lane.
  * A scoped lockout (Max 0 / Percent 0) being breached when a higher-priority
    Min/Percent rule for the SAME carrier allocated into the locked-out scope.

See the module docstring in scripts/fuzz_constraint_combinations.py for the
full invariant list (INV1–INV8).
"""
import glob
import os
import random

import pandas as pd
import pytest

from scripts.fuzz_constraint_combinations import (
    domain_values,
    make_constraints_df,
    check_invariants,
    check_metrics,
)
from components.constraints.processor import apply_constraints_to_data


def _fuzz_snapshot():
    snaps = glob.glob(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "execution logs", "data_snapshots", "comprehensive_data_*.csv"))
    if not snaps:
        pytest.skip("no comprehensive_data snapshot available")
    # Smallest snapshot that is a REAL GVT extract (has a populated rate card) rather
    # than a tiny synthetic fixture. Some fixtures carry a Base Rate of 0 / no rate
    # card, which produces degenerate scenario costs unrelated to the constraint
    # engine. Require a non-trivial number of distinct positive rates + ≥10 rows.
    real = []
    for p in snaps:
        try:
            d = pd.read_csv(p)
        except Exception:
            continue
        rates = pd.to_numeric(d.get('Base Rate'), errors='coerce').dropna()
        if len(d) >= 10 and (rates > 0).sum() >= 5 and rates[rates > 0].nunique() >= 3:
            real.append((len(d), p))
    if not real:
        pytest.skip("no realistic comprehensive_data snapshot available")
    return min(real)[1]  # smallest realistic one keeps the fuzz fast


@pytest.fixture(scope="module")
def data():
    return pd.read_csv(_fuzz_snapshot())


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_crash_no_violation(data, seed):
    """A batch of random constraint combinations must never crash and must never
    violate a correctness invariant."""
    rng = random.Random(seed)
    dom = domain_values(data)
    failures = []
    for i in range(25):
        cdf = make_constraints_df(rng, dom, rng.randint(1, 5))
        try:
            constrained, unconstrained, summary, max_carriers, fc_exclusions, *_ = \
                apply_constraints_to_data(data.copy(), cdf, rate_data=data)
        except Exception as e:  # INV8: no unhandled exception
            failures.append(f"[seed{seed} case{i}] CRASH {type(e).__name__}: {e}")
            continue
        viol = check_invariants(i, data, constrained, unconstrained, summary,
                                max_carriers, fc_exclusions, cdf, dom)
        viol += check_metrics(i, constrained, unconstrained, data, max_carriers, fc_exclusions)
        failures.extend(f"[seed{seed} case{i}] {v}" for v in viol)

    assert not failures, "Constraint-combination invariants violated:\n" + "\n".join(failures[:20])


def test_lockout_beats_higher_priority_min(data):
    """Regression: a Max-0 lockout must hold even when a higher-priority Min for the
    SAME carrier targets the locked-out scope."""
    carrier = data['Dray SCAC(FL)'].dropna().iloc[0]
    port = data['Discharged Port'].dropna().iloc[0]
    cols = [
        'Priority Score', 'Carrier', 'Port', 'Category', 'Lane', 'Week Number',
        'Day of Week', 'Terminal', 'SSL', 'Vessel',
        'Maximum Container Count', 'Minimum Container Count', 'Percent Allocation',
        'Excluded FC',
    ]
    cdf = pd.DataFrame([
        # higher priority: force a big minimum onto the carrier, globally
        {**{c: None for c in cols}, 'Priority Score': 9, 'Carrier': carrier,
         'Minimum Container Count': 50},
        # lower priority: lock the same carrier out of one port
        {**{c: None for c in cols}, 'Priority Score': 1, 'Carrier': carrier,
         'Port': port, 'Maximum Container Count': 0},
    ], columns=cols)

    constrained, unconstrained, summary, max_carriers, fc_exclusions, *_ = \
        apply_constraints_to_data(data.copy(), cdf, rate_data=data)
    dom = domain_values(data)
    viol = check_invariants(0, data, constrained, unconstrained, summary,
                            max_carriers, fc_exclusions, cdf, dom)
    lockout_viol = [v for v in viol if v.startswith('INV4')]
    assert not lockout_viol, "Lockout breached by higher-priority min: " + "; ".join(lockout_viol)
