# Feature Inventory — Tender Optimization App

Full feature set, confirmed working on Streamlit Cloud after the dependency fix
and the incremental re-integration of all logic.

## 1. Data pipeline
- Four Excel uploaders: **GVT**, **Rate**, **Performance**, **Constraints**.
- Load + merge + validate; derive **Week Number** and **Day of Week** from Ocean ETA.
- **Robust Ocean ETA parsing** (`parse_ocean_eta`): Excel serials, blanks, and 0
  sentinels handled — no more 1/1/1970.
- **Category canonicalization** (CD/TL); remove future-dated **Closed** containers;
  dedupe containers per lane/week; volume-weighted performance.

## 2. Filtering & rate selection
- Filters: ports, FCs, weeks, SCACs; selection summary.
- **Rate type selector**: Base Rate vs CPC.

## 3. Constraint engine
- 14-column schema; **Carrier = target** (not a filter).
- Scope dims (AND-stacked): Category, Lane, Port, Week, Day of Week, Terminal, SSL, Vessel.
- Amounts: **Maximum**, **Minimum**, **Percent**, **Excluded FC**.
- Priority ordering; **scoped-max ceilings bind across BOTH constrained + unconstrained**.
- Cross-priority crediting; **even weekly day-of-week distribution** (Mon/Tue/Wed/Thu/Fri-Sun).

## 4. PNW standing rules
- Prebuilt per-port constraints (`config/port_constraints/*.csv`; SEA + TIW carry rules).
- **Hunt up-to-130/wk at Tacoma (allocated first, no floor)**, **60-per-vessel cap**,
  **one-vessel-per-carrier** (same-day), **carrier-port lockouts** (RKNE/HJBT∉SEA, AOYV/RDXY∉TIW).
- Per-terminal **peel-pile thresholds** (`config/peel_pile_thresholds.py`).
- Dashboard shows "Applied N standing port constraint(s)" + constrained/unconstrained split.

## 5. Scenarios (Detailed Analysis Table)
- **Current Selection**, **Performance**, **Cheapest Cost**, **Optimized**.
- Optimized = closed-form lowest-coefficient ranking + cascading allocation with growth
  limits (70% cost / 30% perf, 30% max growth, 5-week window). No PuLP/CBC subprocess.

## 6. Reporting
- **Carrier Flip Analysis**: Old Rate / New Rate / Savings (robust lane/FC + port-alias
  lookup), GVT-with-New-SCAC table, GVT pivot, Excel export.
- **Summary tables** (port/SCAC/lane/facility/terminal/week); **Historic Volume**
  (market share, weekly trends, participation); **Missing rate analysis**;
  **top savings**; **performance assignments**.
- `arrow_safe` guards mixed-type GVT columns at render.

## 7. AI assistant (Bedrock chatbot sidebar)
- Analyzes data, prices flips, proposes/applies constraints; multi-turn memory;
  xlsx + Word reports. Credentials from `st.secrets` (Cloud) / `.env` (local).
- Hidden: JBH Allocation Model (separate uploader; commented out in dashboard).

## 8. Infra
- Entry point `streamlit_app.py` → `dashboard.main()`.
- Dependency **floors** in `requirements.txt` (cp313 wheels) — see CLOUD_FAILURE_POSTMORTEM.md.
- Deployment verification: `scripts/check_deployment.py`, `scripts/drive_deployment.py`.
