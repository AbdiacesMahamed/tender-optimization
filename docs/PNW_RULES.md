# PNW (Pacific Northwest) Allocation Rules

Standing, **always-on** rules for the Pacific Northwest waterfront (Seattle + Tacoma).
These are enforced on **every** optimization run, on top of (and ahead of) anything
a user uploads or asks the assistant for.

## Ports

| Code | Port | Notes |
|---|---|---|
| `SEA` | Seattle | Discharged Port (not a terminal). |
| `TIW` | Tacoma | Discharged Port (not a terminal). |

Both `SEA` and `TIW` are **Discharged Ports** in the GVT data — *not* terminals.
Most PNW rules below are Port-scoped (the Terminal column is left blank); the
exception is **Rule 5** (peel-pile thresholds), which is per-terminal.

### Terminals

The PNW terminals appear in the GVT `Terminal` column under exact, opaque code
strings. The mapping to real terminal names (verified against the PNW GVT extract
and Amazon's Dray Operations terminal registry) is:

| GVT `Terminal` string | Terminal | Port |
|---|---|---|
| `TRM-T004` | Husky Terminal (Tacoma Terminal 4) | `TIW` |
| `TRM-TWUT` | Washington United Terminal (WUT) | `TIW` |
| `TRM-TPCT` | Pierce County Terminal (PCT) | `TIW` |
| `SSA-T18` | Terminal 18 | `SEA` |
| `TERMINAL 5` | Terminal 5 | `SEA` |

## Rule summary

| # | Rule | Type | Status |
|---|---|---|---|
| 0 | Carrier-to-port lockouts (AOYV/RDXY = Seattle, RKNE/HJBT = Tacoma) | Static, per-carrier per-port | ✅ Live (config) |
| 1 | JB Hunt (`HJBT`) = **exactly 130 containers per week** at Tacoma (`TIW`) | Per-carrier, per-week min+max | ✅ Live (generated rows) |
| 2 | **No SCAC** may take more than **60 containers per vessel** | All-carrier, per-vessel cap | ✅ Live (generated rows) |
| 3 | A SCAC may take volume from **only 1 vessel at a time** | Assignment constraint | ✅ Live (post-alloc pass) |
| 4 | If **2+ vessels arrive the same day**, a SCAC may take volume from **only 1** of them | Same-day refinement of #3 | ✅ Live (post-alloc pass) |
| 5 | **Peel-pile qualifying thresholds** are per-terminal at PNW (WUT 40, Husky 45, T18/T5 30, default 80) | Per-terminal group-size floor | ✅ Live (config) |
| 6 | **Empties awareness + prior-week carrier continuity** — reuse the SCAC initially allocated ("sent 10 → pick up 10"), keep each SCAC's per-terminal volume close to prior weeks (predictable pickup locations), informed by the empties-pending-return report | Planning heuristic (look-back) | 🔴 Pending (design) |

Rules 2–5 apply to **PNW ports only** (`SEA` + `TIW`). Rule 1 is Tacoma-only.
Rule 6 is a cross-port planning heuristic surfaced first for PNW.

## Rule 0 — Carrier-to-port lockouts

A carrier that runs at **only one** PNW port is **locked out (Max 0)** of the
other port. A Max 0 lockout allocates nothing to that carrier in the scope *and*
prevents the optimizer from sending it any volume there.

| Carrier | SCAC | Operates at | Encoded as |
|---|---|---|---|
| Waterfront Logistics | `AOYV` | Seattle only | Max 0 lockout at `TIW` (Tacoma) |
| RoadEx | `RDXY` | Seattle only | Max 0 lockout at `TIW` (Tacoma) |
| RoadOne Intermodal | `RKNE` | Tacoma only | Max 0 lockout at `SEA` (Seattle) |
| JB Hunt | `HJBT` | Tacoma only | Max 0 lockout at `SEA` (Seattle) |

Carriers **not** listed above (e.g. Forrest / `FRQT`) are unrestricted in the PNW
and may allocate at both ports.

## Where these rules live

Implemented as **prebuilt per-port constraints** (see
[`config/port_constraints/README.md`](../config/port_constraints/README.md) and
[`components/constraints/prebuilt.py`](../components/constraints/prebuilt.py)).

| File | Contents |
|---|---|
| `config/port_constraints/SEA.csv` | Max 0 lockouts for `RKNE`, `HJBT` (Tacoma-only carriers). |
| `config/port_constraints/TIW.csv` | Max 0 lockouts for `AOYV`, `RDXY` (Seattle-only carriers). |
| `components/constraints/prebuilt.py` | `ENABLED` dict — `"SEA": True`, `"TIW": True`. |
| `config/carrier_scac_names.csv` | Canonical SCAC ↔ carrier-name reference. |
| `config/peel_pile_thresholds.py` | **Rule 5** — per-port/terminal peel-pile thresholds (single source of truth). |

The actual rows (all Priority Score 100, Port-scoped, Max 0):

```
# SEA.csv
Priority Score,Carrier,Port,Maximum Container Count
100,RKNE,SEA,0
100,HJBT,SEA,0

# TIW.csv
Priority Score,Carrier,Port,Maximum Container Count
100,AOYV,TIW,0
100,RDXY,TIW,0
```

(Both files carry the full 14-column constraint schema; only the populated
columns are shown above.)

## Rule 1 — JB Hunt: exactly 130 containers/week at Tacoma

`HJBT` must receive **exactly 130 containers per week** at Tacoma (`TIW`) — a
weekly floor **and** ceiling of 130, applied to **every** week independently.

- **Scope:** Carrier `HJBT`, Port `TIW`, per `Week Number`.
- **Amount:** Minimum 130 **and** Maximum 130 in the same week.
- This complements the JBH allocation model (`config/port_allocation_rules.py`),
  which concentrates volume on Hunt. (Tacoma is not yet a configured port there;
  see that file's `PORT_ALLOCATION_RULES`.)

**How it's enforced:** `build_hunt_weekly_rows()` in
`components/constraints/pnw_vessel_rules.py` generates, for each `Week Number`
present in the TIW data, one **Min-130** and one **Max-130** `HJBT`/`TIW`
constraint row. The Max caps the week at 130; the Min reports a shortfall (the
engine's standard "Partial" status) for any week with fewer than 130 containers
available — which is expected when the data simply doesn't hold 130 Hunt-eligible
containers that week.

## Rule 2 — Per-vessel cap: no SCAC over 60 containers/vessel

No carrier (SCAC) may be allocated more than **60 containers from any single
vessel**, at PNW ports. This is a cap on **every** carrier, per vessel — not a
rule targeting one named carrier.

- **Scope:** PNW ports (`SEA` + `TIW`), per `Vessel`, per SCAC.
- **Amount:** ≤ 60 containers, applied independently to each (vessel, carrier).

**How it's enforced:** `build_per_vessel_cap_rows()` materialises one **Max-60**
constraint row per (PNW port, vessel, carrier) combination present in the data.
Each becomes a scoped ceiling via the engine's tested `scoped_max_ceilings`
machinery (see [[project_scoped_max_ceiling]]), binding that carrier on that
vessel across **both** the constrained and unconstrained tables.

## Rule 3 — One vessel per SCAC at a time

A carrier may take volume from **only one vessel at a time** — each SCAC's PNW
volume must come from a **single vessel**, not spread across several. This is a
combinatorial **assignment** constraint (which vessel each carrier serves), which
no row-by-row constraint can express, so it is enforced as a post-allocation pass.

## Rule 4 — Same-day arrivals: one vessel per SCAC

A refinement of Rule 3 scoped to a single day: when **two or more vessels arrive
on the same day** (same `Ocean ETA` / arrival date at a PNW port), a carrier may
take volume from **only one** of those same-day vessels.

- The GVT data carries `Ocean ETA` (arrival date), `Vessel`, `Week Number`, and
  `Day of Week` per container, so same-day vessel grouping is derivable.

**How Rules 3 & 4 are enforced:** `enforce_one_vessel_per_carrier()` runs on the
allocated frames after constraints are applied. Within each (PNW port,
arrival-day) group that has **2+ vessels**, every carrier is collapsed onto the
single vessel where it already holds the most volume; its containers on the other
same-day vessels have the carrier **cleared** so the scenario optimizer re-homes
them to an eligible carrier. Volume is conserved (no rows dropped).
`check_one_vessel_per_carrier()` is the read-only validator used by the tests and
for diagnostics.

## Rule 5 — Per-terminal peel-pile qualifying thresholds

A **peel pile** is a Vessel + Week + Discharged Port + Terminal group large enough
to warrant a dedicated carrier assignment in the dashboard's Peel Pile Analysis.
The **qualifying threshold** (the minimum container count a group must reach to
surface) is **per-terminal at PNW**, rather than the old global `30`:

| Terminal | GVT `Terminal` string | Threshold |
|---|---|---|
| Washington United (WUT) | `TRM-TWUT` | **40** |
| Husky (Tacoma Terminal 4) | `TRM-T004` | **45** |
| Terminal 18 | `SSA-T18` | **30** |
| Terminal 5 | `TERMINAL 5` | **30** |
| Pierce County (PCT) / any other / blank | `TRM-TPCT`, … | **80** (PNW default) |

- **Scope:** PNW ports (`SEA` + `TIW`), per `Terminal`. Any PNW terminal without
  a specific limit (including PCT and blank terminals) falls back to the PNW
  default of **80**.
- **Outside PNW:** only Oakland (`OAK`) keeps a peel-pile threshold (`30`); every
  other port is effectively disabled (a sentinel threshold no real group reaches),
  so peel piles surface **only** at PNW and OAK.
- This is a *qualifying* threshold (which groups show up), **not** an allocation
  cap — once a group qualifies it is split/assigned exactly as before.

Unlike Rules 0–1 (prebuilt CSV constraints), Rule 5 lives in a dedicated config
module, not the per-port constraint CSVs — see below.

## Rule 6 — Empties awareness + prior-week carrier continuity

> 🔴 **Pending — design captured here, not yet implemented.** This is a *planning
> heuristic* (a look-back that informs future suggestions), not a hard constraint.

### The intent

Allocation planning **looks forward**: we plan the upcoming week(s). But the
**previous and current weeks have already happened** — those allocations are
**locked and cannot be changed**. They are still useful as *signal*: when similar
volume recurs, the assistant should suggest giving it to the **same SCAC that was
initially allocated** the comparable volume, so a carrier that **sent 10**
containers into an FC can be planned to **pick up 10** empties from there in a
future week. The goal is carrier **continuity** — drop-offs and empty pickups
handled by the same carrier — which reduces stranded empties and repositioning.

Three inputs drive this:

1. **Prior-week allocation (look-back).** For the week the user is viewing, also
   read the **immediately preceding week's** actual allocation (already-shipped,
   immutable) to find **which SCAC was initially allocated** each comparable
   volume slice (by Port / Terminal / Lane / FC / Category). That SCAC becomes the
   **preferred carrier** for similar future volume.
2. **Prior per-terminal volume per SCAC (continuity target).** For each
   (SCAC, Terminal), measure **how many containers that carrier handled there in
   recent weeks**, and try to keep the upcoming allocation **close to that number**.
   The point is **predictable pickup locations**: a carrier should keep showing up
   at roughly the same terminals, at roughly the same volume, week over week,
   rather than being scattered across terminals by a purely cost-driven solve. See
   the dedicated subsection below.
3. **Empties at the FC.** The empties-pending-return report (below) tells us
   **how many empty containers are sitting at / pending return from each port**,
   bucketed by how long they've dwelled. High empty counts at a location are the
   pickup opportunity to pair with that location's outbound (sent) volume.

The assistant should be **aware of the empties** and combine these: *"Terminal X
has N empties pending (dwell bucket …); carrier `SCAC` handled ~M containers there
last week and was the carrier initially allocated the comparable inbound volume —
suggest `SCAC` for the empty pickup so sent ≈ picked-up and `SCAC` keeps its
familiar location."* Current/previous weeks are **read-only context**; only
**future** weeks' suggestions are actionable.

### The empties input file

A sample lives at
[`docs/empties_pending_return_sample.xlsx`](empties_pending_return_sample.xlsx)
(provided by the business: *Containers Pending Empty Return by Gateout Dwell
Bucket*). It is a **pivot report**, not a row-per-container extract:

- **Header row** is the **4th row** (`header=3` when read with pandas); the first
  three rows are title/banner. The first column header is literally `Rows`.
- **Rows = ports**, as **US-prefixed** codes (`USLAX`, `USNYC`, `USOAK`, `USSAV`,
  `USPNW`, …) plus a `Total` row. ⚠️ **`USPNW` is a single combined code** for the
  Pacific Northwest (= GVT `TIW` **+** `SEA`); the GVT data, by contrast, splits
  PNW into `TIW` and `SEA`. Any join to GVT must map `USPNW` ↔ {`TIW`, `SEA`} and
  strip the `US` prefix for the other ports (`USLAX` → `LAX`, etc.).
- **Columns = "Gateout Dwell" buckets** — days since gate-out that the empty has
  been pending return: `I. <5`, `II. 5-10`, `III. 11-15`, `IV. 16-20`,
  `V. 21-30`, `VI. 31-40`, `VII. 41-50`, `VIII. 51-60`, `IX. 60+`, and `Total`.
  (Note the buckets are **not** in left-to-right day order in the sheet — `IX. 60+`
  sits between `IV` and `V` — so select columns by **label**, never by position.)
- **Values = container counts** pending empty return for that (port, dwell bucket).
  Blanks mean zero. Example: `USPNW` total = 355 empties; `USLAX` total = 3667.

This file is **port-level only** — it has no carrier (SCAC), FC, or week columns.
So on its own it tells us *where* empties are piling up and *how stale* they are,
but the **"which carrier / which FC"** linkage must come from the **prior-week GVT
allocation** (input 1). Higher dwell buckets (`51-60`, `60+`) are the most urgent
to action.

### Per-terminal volume continuity (input 2, detail)

Beyond *which* carrier (input 1), we also care about *how much* each carrier
handles **at each terminal**, so pickup locations stay predictable. From recent
GVT actuals, compute a **per-(SCAC, Terminal) volume baseline** — the
**trailing-3-week average** container count that SCAC handled at that terminal —
and bias the upcoming allocation to **land near that baseline**:

- **Baseline window:** **trailing 3 weeks**, averaged. (Smooths one-off weeks
  while still adapting; weeks with no data for a (SCAC, Terminal) contribute 0 to
  the average, so a carrier that ran a terminal only once recently gets a small,
  non-zero baseline rather than a spike.)
- **Target, not a hard cap.** It is a **soft preference** the allocator tries to
  honor, balanced against cost, performance, and the hard caps (Rules 0–5 and any
  user/file constraints, which **always win**). It is *not* a Min/Max constraint
  row.
- **Strength (recommended):** treat continuity as a **secondary objective /
  tie-break that sits below cost and performance** — it should decide between
  options that are otherwise close, and discourage gratuitous week-over-week
  terminal churn, but **never override a materially cheaper or better-performing
  option**. Concretely: keep the existing cost/performance objective as-is and add
  a continuity penalty proportional to a SCAC's absolute deviation from its
  per-terminal baseline, scaled so its weight is **~15%** of the blended objective
  (i.e. roughly cost 60 / performance 25 / continuity 15 when normalized). Expose
  the weight as a tunable `opt_continuity_weight` (default ~15, **0 disables**) so
  it can be retuned without code changes. Rationale: the business goal is
  *predictable* locations, not *fixed* ones — a light, always-applied nudge plus
  tie-break achieves stability without sacrificing the cost/performance wins the
  optimizer exists to find.
- **Direction:** prefer giving a carrier its accustomed terminal(s) at roughly its
  accustomed volume; avoid large swings in a SCAC's terminal mix unless cost/caps
  force it. Think "stay close to the trailing-3-week per-terminal split," not
  "exactly reproduce it."
- **Scope:** per `(Dray SCAC(FL), Discharged Port, Terminal)`. At PNW this uses the
  GVT terminal strings in the table above (`TRM-T004`, `TRM-TWUT`, etc.).
- **Where it would plug in:** the scenario allocators
  ([`components/scenarios/strategies.py`](../components/scenarios/strategies.py))
  and the LP/optimized path
  ([`optimization/`](../optimization/)) — as a penalty/objective term that rewards
  staying near the baseline, **after** hard constraints are applied. This is the
  part of Rule 6 that is **allocation-affecting** rather than purely advisory.

### Constrained allocations honor the baseline too

The continuity baseline applies to **both** allocation paths — not just the
free/unconstrained optimizer:

- **Within the optimizer (unconstrained pool):** the soft penalty above steers the
  cost/performance solve toward each SCAC's accustomed terminals.
- **Within constraint application (constrained rows):** when a user/file
  constraint assigns volume to a SCAC **without naming a Terminal** (Terminal scope
  left blank), the processor should use that **SCAC's trailing-3-week terminal
  history to choose *which* containers** (i.e. which terminals' rows) to pull to
  satisfy the constraint — preferring the terminals where that carrier already runs
  volume, in proportion to its baseline — so the constraint keeps the carrier's
  per-terminal volume **similar to recent weeks** instead of grabbing an arbitrary
  set of rows.

  Example: a rule says *"give `RKNE` 50 containers at `TIW`"* with no Terminal. If
  `RKNE`'s trailing-3-week TIW history is ~70% `TRM-T004` / ~30% `TRM-TWUT`, the
  processor fills the 50 by drawing ≈35 from `TRM-T004` rows and ≈15 from
  `TRM-TWUT` rows (subject to availability), rather than whatever rows sort first.
  This is **container selection within an already-decided constraint** — it changes
  *which* containers satisfy the rule, never the rule's target count, and never
  overrides an explicit Terminal the user *did* provide.
- **Precedence:** an explicit Terminal on the constraint always wins. The history
  fallback only fills the gap when the Terminal scope is blank.

### Planned approach (for review before coding)

1. **Look-back read:** when loading week *W*, also load week *W-1* (and optionally
   the current in-progress week) as **read-only** actuals. Do not let them flow
   into the editable allocation — they are immutable context.
2. **Continuity map:** from *W-1* actuals, build `preferred_scac[scope] = SCAC`
   keyed by the comparable slice (Port/Terminal/Lane/FC/Category) — the carrier
   **initially allocated** that volume.
3. **Per-terminal baseline:** from the **trailing 3 weeks** of actuals, build
   `baseline_volume[(SCAC, Port, Terminal)]` = the 3-week **average** container
   count that SCAC handled at that terminal — the target volume to stay near for
   predictable pickup locations (input 2). Also derive each SCAC's per-terminal
   **share** within a port (used by step 6 for container selection).
4. **Empties join:** parse the empties pivot (`header=3`, select dwell columns by
   label), normalize port codes (`USPNW` → `TIW`+`SEA`, strip `US`), and attach
   per-port empty counts (weighted toward high-dwell buckets) as a pickup signal.
5. **Allocation bias (soft, optimizer path):** add a continuity penalty term to the
   scenario + LP allocators that rewards landing a SCAC near its `baseline_volume`
   at each terminal, applied **after** hard constraints (Rules 0–5, user/file caps)
   so those always win. Weight `opt_continuity_weight` ≈ **15** (of a cost-60 /
   perf-25 / continuity-15 blend); **0 disables**.
6. **History-guided container selection (constrained path):** in
   `apply_constraints_to_data`, when a constraint targets a SCAC with a **blank
   Terminal**, choose which rows satisfy it by the SCAC's trailing-3-week
   per-terminal **share** (step 3) instead of arbitrary row order — keeping that
   carrier's per-terminal volume close to recent weeks. An explicit Terminal on the
   constraint overrides this entirely. Changes *which* containers fill the target,
   never the target count.
7. **Suggestion (advisory, not a hard rule):** for upcoming similar volume,
   **recommend** the `preferred_scac`, framed as "sent ≈ pick-up" so the same
   carrier handles the empty return and keeps its familiar terminal. Surfaced by the
   assistant, not a Max/Min constraint.
8. **Assistant awareness:** expose the empties summary, continuity map, and
   per-terminal baselines to the chatbot (a tool or context block) so it can answer
   "who should pick up the empties at <port>?", "which carrier had this volume last
   week?", and "is <SCAC> near its usual volume at <terminal>?".

**Resolved design choices:**
- **Baseline window:** trailing **3 weeks**, averaged.
- **Bias strength:** secondary tie-break **below cost & performance** — weight ≈15%
  (`opt_continuity_weight`, 0 = off); never overrides a materially cheaper/better
  option, only breaks near-ties and discourages churn.
- **Constrained allocations:** also honored — blank-Terminal constraints select
  containers by the SCAC's per-terminal history; explicit Terminal always wins.

**Open questions still to settle before building:** the exact slice for "comparable
volume" in the *advisory* map (Port? Terminal? Lane? FC?); how to weight the dwell
buckets into an urgency score; and how `USPNW` empties split back across `TIW` vs
`SEA`.

## Implementation (Rules 1–4)

All four rules live in
[`components/constraints/pnw_vessel_rules.py`](../components/constraints/pnw_vessel_rules.py)
(pure functions over DataFrames) and are wired into the pipeline in two places:

| Rule | Mechanism | Generated / run where |
|---|---|---|
| 1 | Per-week Min-130 + Max-130 `HJBT`/`TIW` constraint rows | `build_hunt_weekly_rows()` → merged via `merge_prebuilt_first(user, data)` |
| 2 | Max-60 row per (PNW port, vessel, carrier) **+** a post-allocation safety net across both tables | `build_per_vessel_cap_rows()` (merged) **and** `enforce_per_vessel_cap_across()` (post-alloc) |
| 3+4 | Post-allocation pass across both tables: collapse each carrier to one vessel among same-day arrivals; clear the rest | `enforce_one_vessel_per_carrier_across()` |

**Wiring** (`dashboard.py`):

1. `merge_prebuilt_first(constraints_df, final_filtered_data)` — the second arg
   makes `load_pnw_generated_constraints(data)` generate the Rule 1 + Rule 2 rows
   and merge them into the always-on front block (tagged `Prebuilt:PNW`), so they
   process ahead of user rules and inherit the prebuilt precedence guarantee.
2. After `apply_constraints_to_data(...)`, two post-allocation passes run **across
   the combined constrained + unconstrained tables** (the rules bind on a carrier's
   *total* PNW volume, not within either table alone):
   `enforce_per_vessel_cap_across()` (Rule 2 safety net), then
   `enforce_one_vessel_per_carrier_across()` (Rules 3 & 4).

**Why the post-allocation safety nets (not just the generated rows):** the
generated Max-60 rows only bind for (carrier, vessel) pairs present in the *input*.
The scenario optimizer can later move a carrier **onto** a vessel it wasn't on
(escaping that cap) or split a carrier's volume across the constrained and
unconstrained tables (which a per-table pass misses). The `_across` passes operate
on a carrier's **total** PNW volume after allocation, so the caps hold end-to-end.

### Rule 0 ↔ Rule 2 interaction (regression-tested)

Two bugs surfaced when auditing the larger `GVT 6-30.xlsx` extract (both fixed):

1. **Lockout bypass via re-home.** The scoped-max over-cap re-home step
   (`processor.py`) reassigned bumped volume to "any alternate carrier on the lane"
   — including one **locked out** of that port (e.g. capped TIW volume re-homed onto
   AOYV, banned from TIW). Fixed with `compute_scoped_lockouts()` /
   `carrier_locked_out()`: the re-home now skips locked-out candidates, and the
   unconstrained-table sweep also **strips a locked-out carrier off its own original
   rows** (a Max-0 lockout previously only blocked *new* assignment, leaving a
   carrier's pre-existing at-port volume in the unconstrained remainder).
2. **Cap rows for locked-out carriers.** `build_per_vessel_cap_rows()` was emitting
   a Max-60 row for, e.g., `RKNE@SEA` — but a Max-60 "permission" contradicts RKNE's
   Max-0 SEA lockout. It now skips any (carrier, port) in `PORT_LOCKED_OUT_CARRIERS`.

**Resolved design choices** (settled with the business):

- Rule 1 "exactly 130" = per-week Min-130 **and** Max-130. Weeks with < 130
  available report a Min shortfall (expected — the data lacks the volume), the Max
  is never exceeded.
- Rule 3 "at a time" = **same arrival day** (Rule 4), grouping by `Ocean ETA`
  date. The rule only bites on days a PNW port has 2+ vessels.
- **Tie-break:** a carrier keeps the vessel where it already holds the most
  containers (ties broken by vessel name for determinism).
- **Displaced volume:** the carrier is cleared on the losing vessels so the
  scenario optimizer re-homes those containers; nothing is dropped.

## Allocation-engine behavior affecting PNW (added 2026-06-30)

Two general changes to the constraint allocator
([`components/constraints/processor.py`](../components/constraints/processor.py)
`apply_constraints_to_data`) materially change how PNW rules play out. Neither is
PNW-specific code, but both were validated against PNW cases.

### Even weekly (day-of-week) distribution — always on

When a constraint allocates *N* containers, the engine now spreads them
**round-robin across day-of-week buckets** derived from each row's `Ocean ETA`,
instead of draining the earliest day first. **Friday, Saturday and Sunday collapse
into a single `Fri-Sun` bucket**, leaving five buckets: `Mon`, `Tue`, `Wed`,
`Thu`, `Fri-Sun`. The split is best-effort (need not be perfectly even) and never
sacrifices the target — a spill pass tops up from any remaining rows (including
rows with no parseable day) if a thin day can't fill its quota.

- **Why this matters for PNW:** any PNW allocation that spans multiple arrival
  days now distributes volume across the week rather than concentrating it on the
  first day's containers. This is the same `Day of Week` column (Excel WEEKDAY,
  Sun=1 … Sat=7) used by **Rule 4** (same-day arrivals) — the weekday bucketing
  here is a *spread* heuristic, distinct from Rule 4's still-pending
  one-vessel-per-same-day-arrival assignment constraint.
- **Helpers:** `day_bucket(dow)`, `round_robin_quota(target, caps)`,
  `bucket_iter_order(caps)` at module scope in `processor.py`.

### Disjoint-scope caps no longer cannibalize each other (bug fix)

The cumulative cross-priority credit (the "a broader rule is the carrier's total
ceiling" semantic) previously keyed only on `(carrier, Port, Category)` and
**ignored Terminal / Vessel / SSL / Week / Lane / Day**. At PNW — where caps are
naturally **per-vessel** (Rule 2) and **per-terminal** (Rule 5 scoping) — this let
two *disjoint* same-port caps on one carrier wrongly subtract from each other.

> **Concrete PNW failure (now fixed):** `HJBT` max 40 on `VESSEL_A` **+** `HJBT`
> max 15 on terminal `TRM-TWUT` (both at `TIW`). The 40 allocated to VESSEL_A was
> subtracted from the terminal rule's target → the terminal rule allocated **0**,
> leaving 60 HJBT over-cap on that terminal in the unconstrained table.

`_lookup_carrier_scope_total` now counts by **exact scope containment**: it rebuilds
the constraint's full scope mask via `build_scope_filters` (every dimension) and
tallies only previously-allocated containers whose source row falls *inside* that
mask. A genuinely nested earlier rule (e.g. a lane within a port) still credits a
broader rule; disjoint scopes (different vessel/terminal/week) contribute nothing.
This makes the credit logic agree with the scoped-max ceilings, which were already
hard across all scope dimensions on **both** the constrained and unconstrained
tables — so "only 40 on a vessel" (or a terminal, port, or any combination) is now
respected end-to-end for both Min (floor) and Max/Percent (ceiling).

### Tests

`tests/test_even_distribution_and_scoping.py` — round-robin/day-bucket units,
even-spread end-to-end (incl. weekend-collapse, thin-day, and no-`Day of Week`
cases), and vessel/terminal/port × Min/Max/Percent on both tables, including the
vessel-cap-plus-terminal-cap combination that exposed the credit bug.

## How to change a rule

- **Add/adjust a carrier-port restriction:** edit the relevant port CSV — add a
  Port-scoped row with `Maximum Container Count = 0` for the carrier to lock out.
  No engine code changes are needed.
- **Remove a restriction:** delete the carrier's row from the port CSV.
- **Disable all PNW rules:** set `"SEA"` / `"TIW"` to `False` in the `ENABLED`
  dict in `components/constraints/prebuilt.py` (or flip the master
  `PREBUILT_CONSTRAINTS_ENABLED` switch to disable every port at once).
- **Adjust a peel-pile threshold (Rule 5):** edit the tables in
  `config/peel_pile_thresholds.py` — `PNW_TERMINAL_THRESHOLDS` (per-terminal),
  `PNW_DEFAULT_THRESHOLD` (PNW fallback), or `PORT_THRESHOLDS` (other ports). No
  engine code changes are needed.
- **Adjust the vessel rules (Rules 1–4):** edit the config constants at the top of
  `components/constraints/pnw_vessel_rules.py` — `HUNT_WEEKLY_EXACT` (130),
  `PER_VESSEL_MAX` (60), `PNW_PORTS`, `HUNT_SCAC`/`HUNT_PORT`. No other code
  changes needed to retune the numbers.

## Tests

`tests/test_prebuilt_constraints.py` (Rule 0):
- `test_tiw_locks_out_seattle_only_carriers` — AOYV & RDXY are Max 0 at TIW.
- `test_sea_locks_out_tacoma_only_carriers` — RKNE & HJBT are Max 0 at SEA.

`tests/test_pnw_vessel_rules.py` (Rules 1–4):
- Rule 1: one Min-130 + one Max-130 row per TIW week; empty without TIW data.
- Rule 2: one Max-60 row per (port, vessel, carrier), de-duped, PNW-only,
  **skips locked-out carriers**, and **enforced end-to-end** through
  `apply_constraints_to_data` (HJBT capped at 60 on a vessel given 80).
- Rule 2 safety net: `enforce_per_vessel_cap_across()` trims a carrier the optimizer
  moved onto a vessel to ≤ 60 across both tables; no-op when within cap.
- Rules 3/4: detects + fixes a same-day two-vessel split (keeps the bigger vessel,
  clears the rest, conserves volume); no-ops for single-vessel days, different-day
  vessels, and non-PNW ports; `_across` variant catches a split that spans the
  constrained and unconstrained tables.
- Rule 0 regression: a locked-out carrier's **original** at-port volume is stripped
  from the unconstrained table (not just blocked from new assignment).

`tests/test_peel_pile_thresholds.py` (Rule 5):
- Per-terminal PNW limits (WUT 40, Husky 45, T18/T5 30), case-insensitive lookup.
- PCT/blank/unknown PNW terminals fall back to the 80 default.
- OAK stays at 30; all other ports are disabled.

### Auditing real data

`scripts/audit_pnw_rules.py` runs any GVT file(s) through the full pipeline and
prints a per-rule verdict. Verified against **two** extracts — `PNW GVT data.xlsx`
(670 PNW containers) and `GVT 6-30.xlsx` (3,706 PNW containers across 44 same-day
multi-vessel groups): **both pass all rules** (0 lockout breaches, 0 vessel-cap
breaches, 0 same-day multi-vessel breaches, HJBT/TIW ≤ 130/week).

## Related

- `TIW_SEA_constraint_report.md` — a worked example of how Priority order and
  frozen-pool percentages played out on a real PNW upload.
- [`config/carrier_mapping.py`](../config/carrier_mapping.py) — SCAC ↔ name
  mapping used for display and resolution.
- [`docs/empties_pending_return_sample.xlsx`](empties_pending_return_sample.xlsx)
  — sample *Containers Pending Empty Return by Gateout Dwell Bucket* report; the
  empties input for **Rule 6** (port-level pivot; `USPNW` = `TIW`+`SEA`).
