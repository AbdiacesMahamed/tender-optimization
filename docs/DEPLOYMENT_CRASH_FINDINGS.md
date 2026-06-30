# Hosted App Crash — Findings & Suggestions

Status: **unresolved on Streamlit Community Cloud** as of 2026-06-30. The app runs
fine locally but crashes when GVT + Rate data are loaded on the hosted tier.
This doc captures what we found, what we ruled out, and what to try next, so the
next debugging session doesn't start from zero.

---

## The symptom

The Streamlit Cloud log shows one of these, with **no Python traceback**:

```
The service has encountered an error while checking the health of the Streamlit app:
Get "http://localhost:8501/healthz": read tcp ... read: connection reset by peer
```
or
```
Get "http://localhost:8501/script-health-check": EOF
```

**What this means:** these are messages from Streamlit Cloud's *external health
checker*, not from the app. They mean the Streamlit **process died or stopped
responding** — the checker just reports the dropped socket. "connection reset" /
"EOF" with **no traceback** is the signature of a **SIGKILL**, which on a hosted
PaaS almost always means an **out-of-memory (OOM) kill**. A normal Python
exception would NOT look like this — Streamlit catches those and shows a red
error box in the browser.

Key tell: **local works, hosted dies.** The difference is the resource ceiling —
Streamlit Community Cloud's free tier is ~1 GB RAM. Local has more. So the
prime suspect throughout has been **memory**, not logic.

---

## What we found (root causes confirmed & fixed)

1. **Arrow serialization crash on a mixed-type column** — FIXED (`arrow_safe`).
   - `st.dataframe` serializes frames to Arrow via pyarrow. A passthrough GVT
     column (`Carp Appointment`) held **mixed python types in one `object`
     column** (some `int`, some text/blank). pyarrow raised
     `ArrowTypeError: Expected bytes, got a 'int' object`, which killed the run.
   - Fix: `components/core/utils.py::arrow_safe()` coerces any mixed-type object
     column to string before display; applied at the analysis-table, constrained-
     table, and GVT-flip render sites. Regression test: `tests/test_arrow_safe.py`.
   - NOTE: this was a *real* exception-style crash (distinct from the OOM one).

2. **A CBC solver subprocess per Lane×Week group** — FIXED (closed-form optimum).
   - The optimizer solved a tiny LP per group via PuLP's CBC backend, spawning
     **one external CBC process per group — hundreds per page render.** This
     (a) flooded the logs with `Welcome to the CBC MILP Solver ...` banners, and
     (b) piled up subprocess memory — a strong OOM contributor on a 1 GB tier.
   - The per-group problem is linear with one sum-equality constraint and box
     bounds, so the optimum is closed-form: **all volume to the lowest-coefficient
     carrier** (ties → cheaper rate). Replaced the solve with that direct
     computation in `optimization/linear_programming.py`. Zero subprocesses, zero
     solver memory, no banner. 153 optimizer tests pass with identical results.

3. **Diagnostic logging was silently disabled** — FIXED.
   - `logging.basicConfig()` is a **no-op** when the root logger already has
     handlers, and **Streamlit configures the root logger at import**. So every
     breadcrumb we added was discarded — which is why the hosted logs only ever
     showed CBC spam and never our lines. Fixed by attaching a dedicated handler
     to the `tender_dashboard` logger (`propagate=False`) and flushing after each
     stage (a SIGKILL drops buffered output).

---

## What we ruled out

- **Not the chatbot / filter-awareness work** — those modules import and run
  clean; the crash predates interacting with them.
- **Not a clean Python exception in `main()`** — a top-level crash guard was
  added (`dashboard._run_with_crash_guard`) that catches exceptions and renders
  the traceback in the UI. The app still died with `EOF`/reset → it's a process
  kill, not an exception the guard can catch.
- **`msg=False` alone did NOT silence CBC** on the hosted build — the binary
  writes its banner straight to OS file descriptors 1/2, which PuLP's flag
  doesn't always intercept. (Now moot: the solver is gone entirely.)

---

## Still open / not yet confirmed

- **No commit in the debugging session was confirmed to load fully end-to-end**
  on the hosted tier. The one render the user saw ("appearing now") still crashed
  on the Carrier Flip Analysis.
- **The bare app reportedly still failed** even with all heavy sections gated
  OFF (commit `428780c`, feature flags). If that observation is accurate, the
  killer is **upstream of every gated section** — i.e. in the *core data
  pipeline itself* (`load_data_files` → `merge_all_data` →
  `create_comprehensive_data`) or simply **loading the user's large file exceeds
  ~1 GB on its own**. This is the most important lead to pursue next.

---

## Suggestions / next steps (in priority order)

1. **Confirm whether it's pure data size / memory.**
   - Note the GVT row count and file size. If the merged/comprehensive frame is
     large (hundreds of thousands of rows × many columns), simply holding several
     copies (`GVTdata`, `merged_data`, `comprehensive_data`, `final_filtered_data`,
     plus the per-container explode) can exceed 1 GB before any feature runs.
   - Quick test: load a **small slice** of the same file (e.g. one week, one
     port). If the small file loads and the full one doesn't, it's memory/size,
     full stop.

2. **Upgrade the hosting resources** (most direct fix if it's OOM).
   - Streamlit Community Cloud free tier ≈ 1 GB. Move to a tier/host with more
     RAM (paid Streamlit, or run the container on a box with 4–8 GB). This likely
     resolves it without further code surgery.

3. **Reduce peak memory in the core pipeline** (if staying on 1 GB):
   - Avoid keeping multiple full copies. `create_comprehensive_data` currently
     just `.copy()`s `merged_data` — operate in place or drop intermediates with
     `del` + let GC reclaim.
   - Read only needed columns from the GVT/Rate files (`usecols`), and downcast
     dtypes (`category` for repeated strings, smaller int/float).
   - The Carrier Flip Analysis explodes GVT to one row per container — the single
     largest allocation. Keep it gated/lazy (it already is) and/or stream it.

4. **Make the breadcrumbs tell you where memory peaks.**
   - `dashboard._stage(...)` now logs RSS (MB) at each milestone (psutil is in
     requirements). On the hosted logs, read the **last `TENDER stage:` line**
     before the process dies and its RSS — that names the exact step and how
     close to the ceiling it was. (Restart the app / clear the log buffer first;
     the panel keeps old history above the deploy markers, which is misleading.)

5. **One requirements file.** The repo has both `requirements.txt` and
   `pyproject.toml`; Streamlit warns and uses `requirements.txt`. Consolidate to
   avoid drift.

6. **Lead-time lock caveat (behavioral, not a crash):** the standing rule freezes
   every container within 3 days of Ocean ETA. On historical data (past ETAs) it
   freezes the ENTIRE pool, so scenarios show nothing to reallocate — the app
   looks "broken" while working as coded. Guard it to skip locking when it would
   freeze 100% of the pool.

---

## Reference: the fixes worth keeping regardless of revert

If the app is reverted to a pre-session commit to get a stable base, these two
fixes address real bugs and should be re-applied (cherry-picked) on top, since
without them the same crashes return on the same data:

- `arrow_safe()` (Arrow mixed-type crash) — commit `1512e2a`
- closed-form LP (CBC subprocess pile-up) — commit `a15f59d`

All session work is preserved on the backup branch/tag created at revert time
(see `git branch -a` / `git tag`).
