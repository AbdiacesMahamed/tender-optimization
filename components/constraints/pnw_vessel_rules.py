"""PNW (Pacific Northwest) vessel-level allocation rules.

These encode the standing PNW operating rules that go BEYOND the static
per-port carrier lockouts in :mod:`components.constraints.prebuilt`. They are
documented in ``docs/PNW_RULES.md``. Two of them (Rules 1 & 2) reduce to ordinary
scoped constraint rows the existing engine already enforces; the other two
(Rules 3 & 4) are combinatorial assignment rules that no constraint row can
express, so they are enforced as a deterministic POST-ALLOCATION pass.

Rules implemented here
----------------------
* **Rule 1** — JB Hunt (``HJBT``) must receive *exactly* 130 containers per week
  at Tacoma (``TIW``): a per-week Min-130 AND Max-130. Realised by generating one
  Min row and one Max row per ``Week Number`` present in the TIW data
  (:func:`build_hunt_weekly_rows`). The existing constraint engine then enforces
  each as a scoped floor/ceiling.
* **Rule 2** — No SCAC may take more than 60 containers from any single vessel,
  at PNW ports. "Every carrier" is not expressible as a single constraint row
  (Max rows name one target carrier), so we generate one Max-60 row per
  (PNW port, vessel, carrier) actually present in the data
  (:func:`build_per_vessel_cap_rows`). Each becomes a scoped ceiling.
* **Rules 3 & 4** — A SCAC may take volume from only one vessel at a time, and
  when two or more vessels arrive at a PNW port on the same day a SCAC may take
  from only one of them. Enforced by :func:`enforce_one_vessel_per_carrier` on
  the ALLOCATED per-container frame: within each (port, arrival-day) group that
  has 2+ vessels, every carrier is collapsed onto a single vessel (the one where
  it already has the most volume) and its containers on the other same-day
  vessels are released (carrier cleared) so the optimizer re-homes them.

Everything here is a pure function over pandas DataFrames — no Streamlit, no
session state — so it is unit-testable in isolation. Inputs are copied before
mutation; callers get new frames back.
"""
from __future__ import annotations

import pandas as pd

from ..core.utils import parse_container_ids, join_container_ids
from .processor import expected_constraint_columns, resolve_port_filter

# ---------------------------------------------------------------------------
# Configuration — the rule parameters. Edit here to retune the PNW policy.
# ---------------------------------------------------------------------------

#: Discharged-Port codes treated as PNW waterfront for the vessel rules.
PNW_PORTS = ("SEA", "TIW")

#: Rule 1 — JB Hunt SCAC, its port, and the exact weekly volume.
HUNT_SCAC = "HJBT"
HUNT_PORT = "TIW"
HUNT_WEEKLY_EXACT = 130

#: Rule 2 — per-vessel ceiling applied to every carrier at PNW ports.
PER_VESSEL_MAX = 60

#: Rule 0 carrier-to-port lockouts (mirrors the static CSVs in
#: ``config/port_constraints/``). A per-vessel cap row must NOT be generated for a
#: carrier locked out of that port — a Max-60 row reads as "may take up to 60",
#: which would contradict the Max-0 lockout and let banned volume through.
#: Keyed by uppercase Discharged-Port code → set of locked-out SCACs.
PORT_LOCKED_OUT_CARRIERS = {
    "SEA": {"RKNE", "HJBT"},   # Tacoma-only carriers, banned from Seattle
    "TIW": {"AOYV", "RDXY"},   # Seattle-only carriers, banned from Tacoma
}


def _is_locked_out(port, carrier) -> bool:
    """True if ``carrier`` is locked out of ``port`` per the Rule 0 lockouts."""
    return _norm(carrier) in PORT_LOCKED_OUT_CARRIERS.get(_norm(port), set())

#: Priority Score stamped on generated rows. Matches the prebuilt-lockout score
#: (100) so they sit in the always-on band and process ahead of user rules.
GENERATED_PRIORITY = 100

CARRIER_COLS = ("Dray SCAC(FL)", "Carrier")
COUNT_COL = "Container Count"
IDS_COL = "Container Numbers"


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _carrier_col(df: pd.DataFrame) -> str:
    """Return whichever carrier column the frame uses ('Dray SCAC(FL)' or 'Carrier')."""
    for col in CARRIER_COLS:
        if col in df.columns:
            return col
    return CARRIER_COLS[0]


def _norm(val) -> str:
    return str(val).strip().upper() if val is not None and not pd.isna(val) else ""


def _is_pnw_port(value) -> bool:
    return _norm(value) in {p.upper() for p in PNW_PORTS}


def _blank_constraint_row() -> dict:
    """A constraint dict with every canonical column present and empty."""
    return {col: None for col in expected_constraint_columns()}


def _row_count(row) -> int:
    """Container count for an allocated row, preferring the explicit count column."""
    if COUNT_COL in row and pd.notna(row[COUNT_COL]):
        try:
            return int(row[COUNT_COL])
        except (TypeError, ValueError):
            pass
    if IDS_COL in row:
        return len(parse_container_ids(row.get(IDS_COL)))
    return 0


# ---------------------------------------------------------------------------
# Rule 1 — JB Hunt exactly 130/week at Tacoma  → constraint rows
# ---------------------------------------------------------------------------

def build_hunt_weekly_rows(data: pd.DataFrame) -> pd.DataFrame:
    """Generate per-week Min-130 + Max-130 HJBT/TIW rows from the data's weeks.

    One Min row and one Max row per distinct ``Week Number`` that appears in the
    Tacoma (``TIW``) slice of ``data``. Returns an empty (correctly-columned)
    frame when there is no TIW data or no week column. The exact-130 semantic is
    the Min and Max together: the Max caps the week at 130 and the Min reports a
    shortfall when fewer than 130 are available (which the engine surfaces).
    """
    cols = expected_constraint_columns()
    if data is None or len(data) == 0 or "Discharged Port" not in data.columns:
        return pd.DataFrame(columns=cols)
    if "Week Number" not in data.columns:
        return pd.DataFrame(columns=cols)

    tiw = data[data["Discharged Port"].map(_is_pnw_port) &
               (data["Discharged Port"].map(_norm) == HUNT_PORT.upper())]
    if len(tiw) == 0:
        return pd.DataFrame(columns=cols)

    weeks = sorted(int(w) for w in tiw["Week Number"].dropna().unique())
    rows = []
    for wk in weeks:
        base = _blank_constraint_row()
        base.update({"Carrier": HUNT_SCAC, "Port": HUNT_PORT, "Week Number": wk,
                     "Priority Score": GENERATED_PRIORITY})
        max_row = dict(base); max_row["Maximum Container Count"] = HUNT_WEEKLY_EXACT
        min_row = dict(base); min_row["Minimum Container Count"] = HUNT_WEEKLY_EXACT
        rows.append(max_row)
        rows.append(min_row)
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Rule 2 — no SCAC over 60 containers per vessel  → constraint rows
# ---------------------------------------------------------------------------

def build_per_vessel_cap_rows(data: pd.DataFrame) -> pd.DataFrame:
    """Generate a Max-60 row per (PNW port, vessel, carrier) present in the data.

    "No carrier over 60 per vessel" is a cap on EVERY carrier, but a constraint
    row names a single target carrier — so we materialise one capped row per
    (carrier, vessel) combination that actually occurs at a PNW port. Each row is
    Port- and Vessel-scoped, which the engine turns into a scoped ceiling that
    binds that carrier on that vessel across both the constrained and the
    unconstrained tables (the tested scoped-max-ceiling machinery).
    """
    cols = expected_constraint_columns()
    needed = {"Discharged Port", "Vessel"}
    if data is None or len(data) == 0 or not needed.issubset(data.columns):
        return pd.DataFrame(columns=cols)
    carrier_col = _carrier_col(data)
    if carrier_col not in data.columns:
        return pd.DataFrame(columns=cols)

    pnw = data[data["Discharged Port"].map(_is_pnw_port)]
    if len(pnw) == 0:
        return pd.DataFrame(columns=cols)

    seen = set()
    rows = []
    for _, r in pnw.iterrows():
        carrier = str(r[carrier_col]).strip()
        vessel = r["Vessel"]
        port = str(r["Discharged Port"]).strip()
        if not carrier or carrier.lower() in ("nan", "none", ""):
            continue
        if not (vessel is not None and not pd.isna(vessel) and str(vessel).strip()):
            continue
        # Skip carriers locked out of this port (Rule 0): a Max-60 "permission" row
        # would contradict their Max-0 lockout. Their volume is handled by the
        # lockout, not a per-vessel cap.
        if _is_locked_out(port, carrier):
            continue
        key = (port.upper(), _norm(vessel), carrier.upper())
        if key in seen:
            continue
        seen.add(key)
        row = _blank_constraint_row()
        row.update({"Carrier": carrier, "Port": port, "Vessel": str(vessel).strip(),
                    "Maximum Container Count": PER_VESSEL_MAX,
                    "Priority Score": GENERATED_PRIORITY})
        rows.append(row)
    return pd.DataFrame(rows, columns=cols)


# ---------------------------------------------------------------------------
# Combined row generator (Rules 1 + 2)
# ---------------------------------------------------------------------------

def build_pnw_constraint_rows(data: pd.DataFrame) -> pd.DataFrame:
    """All data-derived PNW constraint rows (Rule 1 + Rule 2), concatenated."""
    frames = [build_hunt_weekly_rows(data), build_per_vessel_cap_rows(data)]
    frames = [f for f in frames if f is not None and len(f) > 0]
    cols = expected_constraint_columns()
    if not frames:
        return pd.DataFrame(columns=cols)
    if len(frames) == 1:
        return frames[0][cols]
    # Rebuild from records rather than pd.concat: the per-vessel and per-week
    # frames each have several all-NA columns (unused scope dims), which makes
    # concat emit a dtype-inference FutureWarning. Concatenating the row dicts and
    # re-framing against the fixed column set sidesteps that entirely.
    records = []
    for f in frames:
        records.extend(f[cols].to_dict("records"))
    return pd.DataFrame(records, columns=cols)


# ---------------------------------------------------------------------------
# Rules 3 & 4 — one vessel per carrier (post-allocation enforcement)
# ---------------------------------------------------------------------------

def _arrival_day_series(df: pd.DataFrame) -> pd.Series:
    """A per-row arrival-day key (date) for same-day vessel grouping.

    Uses ``Ocean ETA`` normalised to a calendar date. Rows with no parseable ETA
    get a sentinel so they never group with a real day (each becomes its own
    isolated key, so they are never forced to share a "same-day" decision).
    """
    if "Ocean ETA" in df.columns:
        eta = pd.to_datetime(df["Ocean ETA"], errors="coerce").dt.normalize()
        return eta.where(eta.notna(), other=pd.Series(
            [f"__noeta_{i}__" for i in range(len(df))], index=df.index))
    # No ETA column at all → every row isolated.
    return pd.Series([f"__noeta_{i}__" for i in range(len(df))], index=df.index)


def check_one_vessel_per_carrier(allocated: pd.DataFrame) -> list[dict]:
    """Return violations of Rules 3/4: a carrier drawing from 2+ same-day vessels.

    A violation is one (port, arrival-day, carrier) that spans more than one
    vessel where that day has 2+ vessels at the port. Pure inspection — does not
    modify the frame. Each violation dict carries the port, day, carrier, the
    vessels involved, and the per-vessel container counts.
    """
    violations: list[dict] = []
    if allocated is None or len(allocated) == 0:
        return violations
    needed = {"Discharged Port", "Vessel"}
    if not needed.issubset(allocated.columns):
        return violations
    carrier_col = _carrier_col(allocated)
    if carrier_col not in allocated.columns:
        return violations

    df = allocated.copy()
    df = df[df["Discharged Port"].map(_is_pnw_port)]
    if len(df) == 0:
        return violations
    df["_day"] = _arrival_day_series(df)

    for (port, day), grp in df.groupby(["Discharged Port", "_day"], dropna=False):
        vessels = [v for v in grp["Vessel"].dropna().unique() if str(v).strip()]
        if len(vessels) < 2:
            continue  # Rule 4 only bites when 2+ vessels share the day
        for carrier, cgrp in grp.groupby(grp[carrier_col].astype(str).str.strip()):
            if not carrier or carrier.lower() in ("nan", "none", ""):
                continue
            by_vessel = {}
            for _, r in cgrp.iterrows():
                v = str(r["Vessel"]).strip()
                if not v or v.lower() == "nan":
                    continue
                by_vessel[v] = by_vessel.get(v, 0) + _row_count(r)
            if len(by_vessel) >= 2:
                violations.append({
                    "port": str(port), "day": str(day), "carrier": carrier,
                    "vessels": by_vessel,
                    "kept_vessel": max(by_vessel, key=by_vessel.get),
                })
    return violations


def enforce_one_vessel_per_carrier(allocated: pd.DataFrame):
    """Apply Rules 3/4 to an allocated frame; return ``(fixed_df, changes)``.

    For each (PNW port, arrival-day) group with 2+ vessels, each carrier is
    collapsed onto the single vessel where it already holds the most volume; its
    rows on the OTHER same-day vessels have the carrier cleared (blanked) so the
    downstream optimizer re-homes those containers to an eligible carrier instead
    of leaving a rule-violating assignment. Volume is conserved (no rows dropped).

    ``changes`` is a list of dicts describing every released (carrier, vessel,
    containers) so callers can log/report what moved. Read-only on input: a copy
    is returned.
    """
    if allocated is None or len(allocated) == 0:
        return allocated, []
    needed = {"Discharged Port", "Vessel"}
    if not needed.issubset(allocated.columns):
        return allocated, []
    carrier_col = _carrier_col(allocated)
    if carrier_col not in allocated.columns:
        return allocated, []

    # Reset to a unique positional index for the duration: the constrained frame is
    # built from copied source rows and can carry DUPLICATE index labels, which would
    # make ``df.loc[i]`` return multiple rows. The original index is restored before
    # returning so callers see an unchanged shape.
    df = allocated.copy()
    original_index = df.index
    df = df.reset_index(drop=True)

    pnw_mask = df["Discharged Port"].map(_is_pnw_port)
    work = df[pnw_mask].copy()
    if len(work) == 0:
        return df.set_index(original_index), []
    work["_day"] = _arrival_day_series(work)

    changes: list[dict] = []
    for (port, day), grp in work.groupby(["Discharged Port", "_day"], dropna=False):
        vessels = [v for v in grp["Vessel"].dropna().unique() if str(v).strip()]
        if len(vessels) < 2:
            continue
        for carrier, cgrp in grp.groupby(grp[carrier_col].astype(str).str.strip()):
            if not carrier or carrier.lower() in ("nan", "none", ""):
                continue
            # Volume the carrier holds on each vessel this day (positional indices).
            by_vessel = {}
            for idx, r in cgrp.iterrows():
                v = str(r["Vessel"]).strip()
                if not v or v.lower() == "nan":
                    continue
                by_vessel.setdefault(v, []).append(idx)
            if len(by_vessel) < 2:
                continue
            # Keep the vessel where the carrier has the most containers; release rest.
            counts = {v: sum(_row_count(df.loc[i]) for i in idxs)
                      for v, idxs in by_vessel.items()}
            kept = max(counts, key=lambda v: (counts[v], v))
            for v, idxs in by_vessel.items():
                if v == kept:
                    continue
                for i in idxs:
                    released = _row_count(df.loc[i])
                    if released <= 0:
                        continue
                    # Clear the carrier so the optimizer re-homes these containers.
                    for col in CARRIER_COLS:
                        if col in df.columns:
                            df.at[i, col] = ""
                    changes.append({
                        "port": str(port), "day": str(day), "carrier": carrier,
                        "released_vessel": v, "kept_vessel": kept,
                        "containers": int(released),
                    })
    df.index = original_index
    return df, changes


def enforce_one_vessel_per_carrier_across(constrained: pd.DataFrame,
                                          unconstrained: pd.DataFrame):
    """Apply Rules 3/4 across the COMBINED constrained + unconstrained allocation.

    Rules 3/4 must hold over a carrier's *total* PNW volume, not within each table
    separately — a carrier can have one same-day vessel in the constrained table and
    another in the unconstrained table, which neither single-table call would catch.
    This combines both (tagging their origin), enforces once, then splits the result
    back into ``(constrained, unconstrained, changes)`` with original row identity
    and order preserved.

    Released containers (those NOT on the carrier's kept vessel) always come back on
    the UNCONSTRAINED side with the carrier cleared — they were a rule violation, so
    they must be free for the optimizer to re-home regardless of which table they
    started in.
    """
    c = constrained.copy() if constrained is not None else pd.DataFrame()
    u = unconstrained.copy() if unconstrained is not None else pd.DataFrame()
    if len(c) == 0 and len(u) == 0:
        return c, u, []

    tag = "__pnw_src__"
    if len(c):
        c[tag] = "C"
    if len(u):
        u[tag] = "U"
    combined = pd.concat([d for d in (c, u) if len(d)], ignore_index=True)

    fixed, changes = enforce_one_vessel_per_carrier(combined)
    # Rows whose carrier was cleared by the pass move to the unconstrained side so the
    # optimizer re-homes them; everything else returns to its original table.
    carrier_col = _carrier_col(fixed)
    cleared = fixed[carrier_col].astype(str).str.strip().isin(["", "nan", "none", "None"]) \
        if carrier_col in fixed.columns else pd.Series(False, index=fixed.index)
    new_c = fixed[(fixed[tag] == "C") & (~cleared)].drop(columns=[tag])
    new_u = fixed[(fixed[tag] == "U") | cleared].drop(columns=[tag])
    return new_c.reset_index(drop=True), new_u.reset_index(drop=True), changes


# ---------------------------------------------------------------------------
# Rule 2 — per-vessel cap (post-allocation safety net)
# ---------------------------------------------------------------------------

def check_per_vessel_cap(allocated: pd.DataFrame) -> list[dict]:
    """Return (PNW port, vessel, carrier) groups allocated more than PER_VESSEL_MAX.

    Pure inspection. Generated constraint rows (Rule 2) cap (carrier, vessel) pairs
    present in the INPUT, but the scenario optimizer can later move a carrier ONTO a
    vessel it wasn't on — escaping that cap. This validator catches the result; pair
    it with :func:`enforce_per_vessel_cap` (or the across-tables variant) to fix it.
    """
    out: list[dict] = []
    if allocated is None or len(allocated) == 0:
        return out
    if not {"Discharged Port", "Vessel"}.issubset(allocated.columns):
        return out
    carrier_col = _carrier_col(allocated)
    if carrier_col not in allocated.columns:
        return out
    df = allocated[allocated["Discharged Port"].map(_is_pnw_port)].copy()
    if len(df) == 0:
        return out
    real = df[~df[carrier_col].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE"])]
    g = real.assign(_c=pd.to_numeric(real.get(COUNT_COL), errors="coerce").fillna(0)) \
        .groupby([real["Discharged Port"].astype(str), real["Vessel"].astype(str),
                  real[carrier_col].astype(str).str.strip()])["_c"].sum()
    for (port, vessel, carrier), n in g.items():
        if n > PER_VESSEL_MAX:
            out.append({"port": port, "vessel": vessel, "carrier": carrier,
                        "containers": int(n), "over_by": int(n - PER_VESSEL_MAX)})
    return out


def enforce_per_vessel_cap_across(constrained: pd.DataFrame,
                                  unconstrained: pd.DataFrame):
    """Enforce Rule 2 across the COMBINED allocation; clear over-cap excess.

    For each (PNW port, vessel, carrier) whose TOTAL volume across both tables
    exceeds ``PER_VESSEL_MAX``, the excess containers (taken from the unconstrained
    side first, then constrained) have their carrier cleared so the optimizer
    re-homes them. Rows are split at the container level when they straddle the cap.
    Returns ``(constrained, unconstrained, changes)``. Volume is conserved.

    This is the safety net for Rule 2: the generated Max-60 rows bind during
    constraint application, but only for (carrier, vessel) pairs already in the
    data — a carrier the optimizer later moves onto a vessel would otherwise slip
    past the cap. Run AFTER scenarios reassign, on the final allocation.
    """
    c = constrained.copy() if constrained is not None else pd.DataFrame()
    u = unconstrained.copy() if unconstrained is not None else pd.DataFrame()
    if len(c) == 0 and len(u) == 0:
        return c, u, []
    carrier_col = _carrier_col(c if len(c) else u)
    if not {"Discharged Port", "Vessel"}.issubset((c if len(c) else u).columns):
        return c, u, []

    tag = "__pnw_src__"
    if len(c):
        c[tag] = "C"
    if len(u):
        u[tag] = "U"
    combined = pd.concat([d for d in (c, u) if len(d)], ignore_index=True)
    combined = combined.reset_index(drop=True)

    pnw_mask = combined["Discharged Port"].map(_is_pnw_port)
    real_mask = ~combined[carrier_col].astype(str).str.strip().str.upper().isin(
        ["", "NAN", "NONE"])
    work = combined[pnw_mask & real_mask]

    changes: list[dict] = []
    # Build per-group ordering: release from unconstrained rows first (U before C),
    # so locked/constrained volume is preserved where possible.
    for (port, vessel, carrier), grp in work.groupby(
            [work["Discharged Port"].astype(str), work["Vessel"].astype(str),
             work[carrier_col].astype(str).str.strip()]):
        total = sum(_row_count(combined.loc[i]) for i in grp.index)
        excess = total - PER_VESSEL_MAX
        if excess <= 0:
            continue
        order = sorted(grp.index,
                       key=lambda i: (0 if combined.at[i, tag] == "U" else 1,
                                      -_row_count(combined.loc[i])))
        for i in order:
            if excess <= 0:
                break
            n = _row_count(combined.loc[i])
            if n <= 0:
                continue
            ids = parse_container_ids(combined.at[i, IDS_COL]) if IDS_COL in combined.columns else []
            take = min(excess, n)
            if ids and take < n:
                # Split: keep (n-take) on the carrier; move `take` to a cleared clone.
                keep_ids, move_ids = ids[take:], ids[:take]
                combined.at[i, IDS_COL] = join_container_ids(keep_ids)
                combined.at[i, COUNT_COL] = len(keep_ids)
                clone = combined.loc[i].copy()
                clone[IDS_COL] = join_container_ids(move_ids)
                clone[COUNT_COL] = len(move_ids)
                for col in CARRIER_COLS:
                    if col in combined.columns:
                        clone[col] = ""
                clone[tag] = "U"
                combined = pd.concat([combined, pd.DataFrame([clone])], ignore_index=True)
            else:
                # Clear the whole row (no ids to split, or it's fully over-cap).
                take = n
                for col in CARRIER_COLS:
                    if col in combined.columns:
                        combined.at[i, col] = ""
                combined.at[i, tag] = "U"
            excess -= take
            changes.append({"port": port, "vessel": vessel, "carrier": carrier,
                            "containers": int(take)})

    cleared = combined[carrier_col].astype(str).str.strip().str.upper().isin(
        ["", "NAN", "NONE"]) if carrier_col in combined.columns \
        else pd.Series(True, index=combined.index)
    new_c = combined[(combined[tag] == "C") & (~cleared)].drop(columns=[tag])
    new_u = combined[(combined[tag] == "U") | cleared].drop(columns=[tag])
    return new_c.reset_index(drop=True), new_u.reset_index(drop=True), changes
