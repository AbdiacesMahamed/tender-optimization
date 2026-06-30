# Constraint Rules & Mechanics

The **behavioral reference** for how the constraint engine works — the rules that
govern precedence, scoping, and amounts. This is the *why/what-happens* companion to:

- [`CONSTRAINTS_GUIDE.md`](CONSTRAINTS_GUIDE.md) — user-facing file format + examples.
- [`CONSTRAINTS.md`](CONSTRAINTS.md) — system overview + data flow.
- [`PNW_RULES.md`](PNW_RULES.md) — the standing, always-on PNW port rules.
- [`dev/components-constraints-processor.md`](dev/components-constraints-processor.md) — code-level function reference.

Everything here is implemented in
[`components/constraints/processor.py`](../components/constraints/processor.py)
(`apply_constraints_to_data` and its helpers). When the code and this doc disagree,
the code wins — but please update this doc.

---

## 1. The mental model

A constraint is an instruction to **assign volume to a target carrier**, optionally
within a **scope** (filters), up to/at least/at a given **amount**. Applying the
full constraint set splits the data into two tables:

| Constrained table | Unconstrained table |
|---|---|
| Rows **locked** to a carrier by a constraint. | Everything else. |
| Scenarios (Cheapest/Performance/Optimized) do **not** change these. | Scenarios reallocate these freely. |

**Conservation is invariant:** `Original = Constrained + Unconstrained`, always, at
the container level. Constraints never delete containers — a capped carrier's
overflow stays in the unconstrained pool for other carriers to pick up.

---

## 2. Carrier is the target, not a filter

> **The single most important rule.** `Carrier` is **who the volume is assigned
> to**, *not* a filter on who currently holds it.

A constraint "give ATMI 100 at LAX" means *pull 100 LAX containers (from whatever
carrier currently holds them) and lock them to ATMI* — it does **not** mean "find
containers already on ATMI." Every other column (`Category`, `Lane`, `Port`,
`Week Number`, `Day of Week`, `Terminal`, `SSL`, `Vessel`) **is** a scope filter.
(`build_scope_filters` deliberately omits Carrier.)

---

## 3. Scope filters

The schema (`expected_constraint_columns`) is **14 columns**: the 9 scope filters
above, plus the three amounts (`Maximum`/`Minimum`/`Percent`), `Excluded FC`, and
`Priority Score`.

- **Blank = "any".** An empty filter cell does not restrict that dimension.
- **Filters AND together.** Multiple filters all must match the same row. The more
  filters, the narrower the scope.
- **Matching is normalized**, so casing/whitespace never cause a silent miss:
  - **Category** — both the constraint value *and* the data column are folded to a
    canonical bucket before comparing (`CD` matches `Retail CD`/`FBA FCL`/`FBA LCL`
    and the already-normalized `CD`). See [`config/category_mapping.py`](../config/category_mapping.py).
  - **Port** — shorthand expands via `PORT_ALIASES` (e.g. `NYC`→ its Discharged
    Port set), then matched case/space-insensitively.
  - **Lane** — a short value (≤ 4 chars, e.g. `ABE8`) matches by **suffix** against
    the full 9-char lane (`USNYCABE8`); a long value matches exactly.
  - **Day of Week** — Excel WEEKDAY numbering, **Sun = 1 … Sat = 7**; accepts a
    number or a day name (parsed at load time).
  - **Terminal / SSL / Vessel** — exact match, case/whitespace-normalized.
- **Carrier spelling is auto-resolved** to the spelling that actually exists in the
  data (case-insensitively), so a constraint typed `TraPac` correctly targets
  `TRAPAC` instead of creating a phantom carrier that silently fails to bind.

---

## 4. Priority order

Constraints are processed **highest `Priority Score` first**.

1. Sort by Priority Score, descending.
2. Apply each constraint in turn against the **remaining** (not-yet-claimed) pool.
3. **A container claimed by a higher-priority constraint is gone** — a lower
   priority constraint works only with what's left.
4. Conflicts are therefore resolved by priority, not by file row order.

> **Prebuilt rules sit ahead of priority.** Always-on port rules
> ([`prebuilt.py`](../components/constraints/prebuilt.py),
> e.g. the [PNW lockouts](PNW_RULES.md)) are merged to the **front** of the set, so
> they claim their volume *before* any user rule — even a user rule with a higher
> Priority Score. Priority only orders rules *within* the prebuilt block and
> *within* the user block. See [`config/port_constraints/README.md`](../config/port_constraints/README.md).

---

## 5. Amount types

Each constraint carries **one** amount. All three are evaluated against the
constraint's scope.

### Maximum Container Count — a ceiling
- Locks **up to** N matching containers to the carrier; the rest stay unconstrained.
- The carrier is added to the **exclusion set** (`max_constrained_carriers`) for
  that scope, so scenario optimization won't hand it *more* volume there.
- `Maximum = 0` is a **lockout**: allocate nothing **and** block the optimizer from
  assigning any (used by the PNW carrier-port lockouts).

### Minimum Container Count — a floor
- Guarantees **at least** N matching containers are locked to the carrier.
- If the scope doesn't contain N available containers, the constraint reports a
  **shortfall** (it allocates what exists; it cannot invent volume).

### Percent Allocation — a proportional ceiling
- Targets **P %** of the scope's volume for the carrier (0–100; `0` = lockout).
- **Denominator is the original scope volume**, snapshotted *before any allocation*
  — so "30 %" always means 30 % of the full scope, even if higher-priority rules
  already consumed part of the pool. Percent behaves as a **ceiling**, not a floor.

---

## 6. Scoped maxima are hard ceilings everywhere

A `Maximum` (or `Percent`) cap binds as a **hard ceiling across every scope
dimension** and across **both** tables — not just the rows the file pass happened
to touch.

- `compute_scoped_max_ceilings` pre-scans every Max rule into a
  `{carrier, mask, cap, allocated}` ceiling using the *same* `build_scope_filters`
  as allocation, so the cap covers all matching rows.
- The file pass, the **peel pile** pass, and the scenario optimizer all consult the
  same ceilings (`ceiling_headroom` / `credit_ceilings`), so a manual peel-pile
  override or an optimizer reallocation **cannot bust a cap the user set**. Overflow
  beyond the cap stays unconstrained.
- This holds for a cap scoped to a vessel, a terminal, a port, or any combination.

---

## 7. Cross-priority crediting (no double-dipping)

A **broader rule is the carrier's total ceiling** for its scope. If a high-priority
narrow rule already gave a carrier volume, a later broader rule for the **same
carrier** subtracts what it already has, so the carrier doesn't double-dip across
priorities.

- Crediting is by **exact scope containment** (`_lookup_carrier_scope_total` rebuilds
  the full scope mask and tallies only previously-allocated containers that fall
  *inside* it).
- **Nested scopes credit; disjoint scopes don't.** A lane-within-a-port rule credits
  a later port-wide rule for the same carrier. But two **disjoint** caps on one
  carrier (e.g. `max 40 on VESSEL_A` + `max 15 on terminal TRM-TWUT`, same port) do
  **not** subtract from each other — a previously-fixed bug had the vessel allocation
  cannibalize the terminal rule's target down to 0.

---

## 8. Even weekly (day-of-week) distribution — always on

When a constraint allocates N containers, the engine spreads them **round-robin
across day-of-week buckets** (from each row's `Ocean ETA`) instead of draining the
earliest day first. **Fri/Sat/Sun collapse into one `Fri-Sun` bucket**, leaving
`Mon`, `Tue`, `Wed`, `Thu`, `Fri-Sun`.

- Best-effort, never at the cost of the target: a spill pass tops up from any
  remaining rows (including rows with no parseable day) if a thin day can't fill its
  quota.
- Helpers: `day_bucket`, `round_robin_quota`, `bucket_iter_order` in `processor.py`.

---

## 9. Excluded FC — a facility ban

`Excluded FC` bans a carrier from a facility entirely (requires a `Carrier`).

- The carrier receives **no** containers at that facility in **either** table.
- If the carrier already holds containers there, the engine **reallocates** them:
  1. look in the current data for another carrier serving that lane;
  2. else consult the **rate data** for a capable carrier;
  3. the alternative must have rates for the lane, **not** be excluded from the
     facility itself, and **not** be over its own Maximum.
- If no valid alternative exists, the constraint **fails** (reported in the summary).
- Combine with a `Maximum` to cap a carrier *and* ban it from specific facilities in
  one row.

---

## 10. Pipeline order (end to end)

1. **Prebuilt / always-on rules** merged to the front (PNW, etc.).
2. **User/chatbot constraints**, processed highest Priority first; each claims from
   the remaining pool. → produces the constrained vs. unconstrained split.
3. **Peel pile** allocations applied **after** all constraint rows — they can only
   claim still-unclaimed containers and they honor the scoped-max ceilings (§6).
   See [`CONSTRAINTS_GUIDE.md`](CONSTRAINTS_GUIDE.md) (Peel Pile) and
   [`PNW_RULES.md`](PNW_RULES.md) (Rule 5 thresholds).
4. **Scenario optimization** runs on the **unconstrained** table only, skipping any
   carrier/scope in the exclusion set and respecting the ceilings.

---

## 11. When a constraint matches nothing

`diagnose_no_match` classifies a zero-match constraint so it's actionable:

- **`dead`** — one or more filter *values* are absent from the data entirely (a
  typo, an alias that didn't expand, or a value that only exists under a different
  week/port/category). The most common, most fixable cause.
- **`combination`** — every filter matches rows on its own, but no single row
  satisfies all of them at once (the scope is too narrow — relax one dimension).

A zero-match or shortfall is **not automatically a bug**: a rule can be legitimately
superseded by a higher-priority rule, or out of scope for the loaded data. Triage by
root cause before "fixing."

---

## 12. Quick reference

| Rule | One-liner |
|---|---|
| Carrier = target | `Carrier` is who volume is assigned *to*, not a filter. |
| Blank filter = any | Empty scope cell doesn't restrict that dimension. |
| Filters AND | All specified filters must match the same row. |
| Priority desc | Higher Priority Score processed first; claims are exclusive. |
| Prebuilt first | Always-on port rules outrank any user Priority Score. |
| Max = ceiling | Cap; overflow stays unconstrained; `0` = lockout. |
| Min = floor | At least N; reports shortfall if scope lacks volume. |
| Percent = ceiling | P % of the **original** scope volume; `0` = lockout. |
| Caps are hard everywhere | Scoped max binds across all dims + both tables + peel pile + optimizer. |
| No double-dip | Broader rule credits nested earlier volume; disjoint scopes don't cannibalize. |
| Even spread | Allocations round-robin across Mon/Tue/Wed/Thu/Fri-Sun. |
| Excluded FC | Hard facility ban; triggers reallocation or fails. |
| Conservation | `Original = Constrained + Unconstrained`, always. |
