"""Core property-based stress test for the new agent analysis layer.

Fuzzes diagnose_constraints / repair_constraints / report builders / analysis
memory with thousands of random + adversarial inputs and asserts HARD invariants.
Any violation is printed with the seed so it reproduces. Run:
    .venv/Scripts/python.exe scratch_stress_core.py
"""
import sys, os, io, json, random, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tests.conftest  # streamlit stub
import pandas as pd
import components.chatbot.tools as T
from components.constraints.processor import process_constraints_file, apply_constraints_to_data, parse_container_ids

comp = pd.read_pickle("/tmp/comp_real.pkl")
PORTS = list(comp["Discharged Port"].dropna().unique())
CATS = list(comp["Category"].dropna().unique())
CARRIERS = list(comp["Dray SCAC(FL)"].dropna().unique())
LANES = list(comp["Lane"].dropna().unique())
WEEKS = list(comp["Week Number"].dropna().unique())

# Adversarial value pools — things a sloppy/hostile constraint file might carry.
JUNK = [None, "", "  ", float("nan"), "ZZZ9", "❤", "'; DROP", 1e9, -5, 0, 0.0,
        "100", "1e3", True, [], {}, "NaN", "null"]

def _ids(df):
    s = set()
    for v in df.get("Container Numbers", pd.Series([], dtype=object)).dropna():
        s.update(parse_container_ids(v))
    return s

ORIG_IDS = _ids(comp)

def rand_constraint(rng):
    """A random (often malformed) constraint row over the real schema."""
    row = {c: None for c in T.CONSTRAINT_COLUMNS}
    def maybe(col, choices, p=0.5):
        if rng.random() < p:
            row[col] = rng.choice(choices)
    row["Priority Score"] = rng.choice([rng.randint(1, 20), None, "hi", 9.5, -1])
    maybe("Carrier", CARRIERS + ["ZZZZ", None, "❤", ""], 0.8)
    maybe("Port", PORTS + JUNK, 0.5)
    maybe("Category", CATS + JUNK, 0.4)
    maybe("Lane", [l[-4:] for l in LANES] + LANES + JUNK, 0.3)
    maybe("Week Number", WEEKS + JUNK, 0.2)
    amt = rng.random()
    if amt < 0.3:
        row["Percent Allocation"] = rng.choice([0, 20, 50, 80, 100, 130, -10, 0.5, "50", None])
    elif amt < 0.5:
        row["Maximum Container Count"] = rng.choice([0, 5, 50, 500, 99999, -3, None])
    elif amt < 0.6:
        row["Minimum Container Count"] = rng.choice([0, 5, 5000, None])
    elif amt < 0.65:
        row["Excluded FC"] = rng.choice(["LAX9", "ZZZZ", None])
    return row

def rand_set(rng, n=None):
    n = n if n is not None else rng.randint(0, 25)
    return [rand_constraint(rng) for _ in range(n)]

fails = []
def check(cond, msg, seed, extra=""):
    if not cond:
        fails.append(f"[seed {seed}] {msg} {extra}")

N = 2000
print(f"Fuzzing diagnose+repair with {N} random constraint sets...")
for seed in range(N):
    rng = random.Random(seed)
    cons = rand_set(rng)
    # normalize to working-set shape (what the executor would have)
    ws = [T._normalize_constraint(c) for c in cons]
    for w in ws:
        w["_origin"] = "uploaded"
        w["_problems"] = T.validate_constraint(w, None)
    try:
        diag = T.diagnose_constraints(ws, comp)
    except Exception as e:
        fails.append(f"[seed {seed}] diagnose RAISED: {e}\n{traceback.format_exc()}")
        continue
    try:
        json.dumps(diag)
    except Exception as e:
        check(False, "diagnose not JSON-serializable", seed, str(e))
    try:
        rep = T.repair_constraints(ws, comp, valid_carriers=set(CARRIERS))
    except Exception as e:
        fails.append(f"[seed {seed}] repair RAISED: {e}\n{traceback.format_exc()}")
        continue
    try:
        json.dumps({k: v for k, v in rep.items() if k != "constraints"})
    except Exception as e:
        check(False, "repair (minus constraints) not JSON-serializable", seed, str(e))

    kept = rep["constraints"]
    s = rep["summary"]
    # The report builder must NEVER KeyError on the not-analyzable shape.
    try:
        T.build_analysis_workbook_bytes(diag, constraints_after=kept)
    except Exception as e:
        check(False, "workbook builder raised on diagnose output", seed, str(e))
    # INV1: bookkeeping consistent
    check(s["kept"] == len(kept), "kept count mismatch", seed, f'{s}')
    check(s["kept"] == s["original_count"] - s["dropped"] - s["collapsed"],
          "kept != original - dropped - collapsed", seed, f'{s}')
    # INV2: repair must FIX out-of-range amounts, not just flag them. After repair
    # every surviving row's percent is in [0,100] and caps are non-negative.
    for r in kept:
        pct = r.get("Percent Allocation")
        if pct is not None:
            check(0 <= pct <= 100, "percent STILL out of range after repair", seed, f'{pct}')
        for col in ("Maximum Container Count", "Minimum Container Count"):
            amt = r.get(col)
            if amt is not None:
                check(amt >= 0, f"{col} STILL negative after repair", seed, f'{amt}')
    # INV3: lockouts preserved (count of 0% / max0 rules never decreases)
    def n_lock(rows):
        return sum(1 for r in rows if T._coerce_num(r.get("Percent Allocation")) == 0
                   or T._coerce_num(r.get("Maximum Container Count")) == 0)
    check(n_lock(kept) >= n_lock(ws), "a lockout was dropped by repair", seed,
          f'{n_lock(ws)}->{n_lock(kept)}')
    # INV4: repair does not INCREASE over-subscription
    try:
        diag2 = T.diagnose_constraints(kept, comp)
    except Exception as e:
        fails.append(f"[seed {seed}] re-diagnose RAISED: {e}")
        continue
    over_before = {(o["port"], o["category"]) for o in diag.get("over_subscribed_scopes", [])}
    over_after = {(o["port"], o["category"]) for o in diag2.get("over_subscribed_scopes", [])}
    new_over = over_after - over_before
    check(not new_over, "repair INTRODUCED new over-subscribed scope(s)", seed, f'{new_over}')
    # INV5: idempotency — repairing the repaired set changes nothing material
    rep2 = T.repair_constraints(kept, comp, valid_carriers=set(CARRIERS))
    check(rep2["summary"]["dropped"] == 0,
          "second repair still drops rules (not idempotent)", seed, f'{rep2["summary"]}')

print(f"  diagnose/repair invariants: {len(fails)} failures")

# ---- round-trip: corrected set must be accepted by the REAL processor ----
print("Round-tripping repaired sets through the real processor (200 sets)...")
rt_fail = 0
for seed in range(200):
    rng = random.Random(10_000 + seed)
    ws = [T._normalize_constraint(c) for c in rand_set(rng, rng.randint(1, 15))]
    for w in ws:
        w["_origin"] = "uploaded"
    rep = T.repair_constraints(ws, comp, valid_carriers=set(CARRIERS))
    clean = [r for r in rep["constraints"] if not r.get("_problems")]
    if not clean:
        continue
    try:
        reparsed = process_constraints_file(io.BytesIO(T.constraints_to_excel_bytes(clean)))
        con, unc, summ, mx, ex, logs = apply_constraints_to_data(comp, reparsed, None)
        # container conservation at the ID level
        cu = _ids(con) | _ids(unc)
        if not (cu <= ORIG_IDS):
            rt_fail += 1
            fails.append(f"[seed {10000+seed}] round-trip leaked container IDs not in original")
    except Exception as e:
        rt_fail += 1
        fails.append(f"[seed {10000+seed}] round-trip RAISED: {e}\n{traceback.format_exc()[:300]}")
print(f"  round-trip failures: {rt_fail}")

# ---- report builders on fuzzed diagnoses ----
print("Fuzzing report builders (300 sets, incl. empty/huge)...")
rb_fail = 0
for seed in range(300):
    rng = random.Random(20_000 + seed)
    n = rng.choice([0, 1, 2, 60])
    ws = [T._normalize_constraint(c) for c in rand_set(rng, n)]
    for w in ws:
        w["_origin"] = "uploaded"
    diag = T.diagnose_constraints(ws, comp) if ws else T.diagnose_constraints([], comp)
    rep = T.repair_constraints(ws, comp) if ws else None
    try:
        xb = T.build_analysis_workbook_bytes(diag, constraints_after=(rep or {}).get("constraints"))
        assert isinstance(xb, bytes) and len(xb) > 50
        pd.ExcelFile(io.BytesIO(xb))  # must open
        db = T.build_analysis_report_docx_bytes(diag, repair=rep)
        assert db is None or (isinstance(db, bytes) and len(db) > 50)
    except Exception as e:
        rb_fail += 1
        fails.append(f"[seed {20000+seed}] report builder RAISED: {e}\n{traceback.format_exc()[:300]}")
print(f"  report-builder failures: {rb_fail}")

print("\n" + "=" * 80)
if fails:
    print(f"TOTAL FAILURES: {len(fails)}")
    for f in fails[:40]:
        print(" -", f)
else:
    print("ALL INVARIANTS HELD — 0 failures across ~2500 fuzzed cases.")
