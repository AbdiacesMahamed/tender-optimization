"""Input normalization + eligibility filtering for the JBH Allocation Model.

Implements Section 1 (input requirements), Section 2 (eligibility filters),
and Section 15 (SSL -> terminal fallback) of the reference document. Pure
pandas — no Streamlit — so it is unit-testable in isolation.

The Inbound Container Milestone file is per-container (one row = one container),
unlike the dashboard's aggregated GVT. We normalize header names to a canonical
lowercase schema up front so the rest of the engine can rely on fixed names.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

import pandas as pd

logger = logging.getLogger(__name__)


# Section 1: canonical column schema. Maps canonical name -> list of accepted
# header spellings (lowercased, stripped) seen in real files. Header matching
# is case-insensitive and ignores surrounding whitespace/punctuation.
COLUMN_ALIASES: dict[str, list[str]] = {
    "terminal": ["terminal", "discharge terminal", "term"],
    "facility": ["facility", "fc", "destination", "dest", "final destination"],
    "ssl": ["ssl", "steamship line", "steamship", "carrier line"],
    "vessel": ["vessel", "vessel name", "ship"],
    "category": ["category", "cat", "container category"],
    "container_id": ["container_id", "container id", "container", "container number",
                     "container numbers", "container #", "container#", "containers"],
    "priority_code": ["priority_code", "priority", "priority code", "priority level"],
    "scac": ["scac", "dray scac", "dray scac(fl)", "drayage scac", "carrier", "dray carrier"],
    "ocean_eta": ["ocean_eta", "ocean eta", "eta", "vessel eta", "ocean e.t.a."],
    "term_avail": ["term_avail", "terminal available", "terminal avail", "term avail", "available", "av date"],
    "actual_pu": ["actual_pu", "actual pickup", "actual pu", "pickup", "pickup date", "actual outgate"],
}

# Columns the model strictly requires to do anything useful.
REQUIRED_COLUMNS = ["facility", "category", "container_id", "scac", "ocean_eta"]

# Critical fields counted toward the Section 10 "Missing Field Rate" trigger.
CRITICAL_FIELDS = ["ocean_eta", "terminal", "facility", "container_id"]


def _canon(name: object) -> str:
    """Lowercase, strip, and collapse punctuation/whitespace for header matching."""
    s = re.sub(r"[^a-z0-9]+", " ", str(name).strip().lower()).strip()
    return s


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename input columns to the canonical schema (Section 1).

    Unrecognized columns are kept as-is (lowercased) so nothing is silently
    dropped. Returns a copy.
    """
    lookup = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            lookup[_canon(alias)] = canonical

    rename = {}
    for col in df.columns:
        canon = _canon(col)
        if canon in lookup:
            rename[col] = lookup[canon]
    out = df.rename(columns=rename).copy()

    # Any column not mapped to a canonical name: keep a lowercased version so
    # downstream string ops are predictable, but don't clobber canonical names.
    return out


def validate_columns(df: pd.DataFrame) -> list[str]:
    """Return the list of REQUIRED_COLUMNS missing from a normalized frame."""
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def explode_container_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Split comma/semicolon/pipe/whitespace-separated container cells to one row each.

    The GVT (a.k.a. Inbound Container Milestone) often packs many container IDs
    into a single 'Container Numbers' cell. The allocation model reasons per
    container, so we explode those cells: every other column is duplicated onto
    each resulting row. Rows whose container cell holds a single ID are
    unchanged. Empty/blank IDs are dropped. Returns a copy.
    """
    if "container_id" not in df.columns:
        return df.copy()

    out = df.copy()

    def _split(cell):
        if cell is None or (isinstance(cell, float) and pd.isna(cell)):
            return []
        toks = re.split(r"[,;|\n\r\t ]+", str(cell).strip())
        return [t for t in (tok.strip() for tok in toks) if t and t.lower() != "nan"]

    # Fast path: if no cell is multi-valued AND none are blank/nan, the column is
    # already one-clean-ID-per-row — return as-is to avoid the explode cost.
    as_str = out["container_id"].astype(str).str.strip()
    multi = as_str.str.contains(r"[,;|\s]", regex=True, na=False).any()
    blank = (as_str == "") | (as_str.str.lower() == "nan") | out["container_id"].isna()
    if not multi and not blank.any():
        return out

    out["container_id"] = out["container_id"].apply(_split)
    out = out.explode("container_id", ignore_index=True)
    # Drop rows whose container is empty/NaN after the split (e.g. an all-blank cell).
    keep = out["container_id"].notna() & out["container_id"].astype(str).str.strip().astype(bool)
    out = out[keep]
    return out.reset_index(drop=True)


def filter_to_port(df: pd.DataFrame, port: str) -> pd.DataFrame:
    """Restrict a GVT/milestone frame to one Discharged Port (case-insensitive).

    The GVT spans every port; the allocation model is per-port, so we select the
    rows for the chosen port. If there is no recognizable port column, the frame
    is returned unchanged (single-port file assumed). Returns a copy.
    """
    port_u = str(port).strip().upper()
    for col in ("discharged port", "discharged_port", "port"):
        # Match against canonical-or-raw column names, case-insensitively.
        match = next((c for c in df.columns if _canon(c) == _canon(col)), None)
        if match is not None:
            vals = df[match].astype(str).str.strip().str.upper()
            # Discharged Port may be a bare code ('LAX') or prefixed ('USLAX').
            mask = (vals == port_u) | (vals == f"US{port_u}") | (vals.str.replace("US", "", n=1) == port_u)
            return df[mask].copy()
    return df.copy()


def _contains_any(series: pd.Series, needles: list[str]) -> pd.Series:
    """Case-insensitive substring match against any needle. NaN -> False."""
    s = series.astype(str).str.upper()
    mask = pd.Series(False, index=series.index)
    for n in needles:
        mask |= s.str.contains(re.escape(str(n).upper()), na=False)
    return mask


def apply_ssl_terminal_fallback(df: pd.DataFrame, rules) -> pd.DataFrame:
    """Section 15: infer a blank terminal from the SSL's most common terminal.

    For each SSL, find the terminal it most frequently uses across the file and
    assign that to rows where terminal is blank. If the SSL is also unknown,
    fall back to ``rules.ssl_fallback_default_terminal``. Returns a copy.
    """
    if "terminal" not in df.columns:
        df = df.copy()
        df["terminal"] = pd.NA
    out = df.copy()

    blank = out["terminal"].isna() | (out["terminal"].astype(str).str.strip() == "")
    if not blank.any():
        return out

    # Most common terminal per SSL, computed from rows that DO have a terminal.
    known = out[~blank]
    ssl_to_terminal: dict[str, str] = {}
    if "ssl" in out.columns and not known.empty:
        for ssl_val, grp in known.groupby(known["ssl"].astype(str).str.strip()):
            mode = grp["terminal"].astype(str).str.strip().mode()
            if len(mode):
                ssl_to_terminal[ssl_val] = mode.iloc[0]

    default_terminal = rules.ssl_fallback_default_terminal

    def _infer(row):
        ssl_val = str(row.get("ssl", "")).strip() if "ssl" in out.columns else ""
        return ssl_to_terminal.get(ssl_val, default_terminal)

    out.loc[blank, "terminal"] = out.loc[blank].apply(_infer, axis=1)
    n_filled = int(blank.sum())
    if n_filled:
        logger.info("SSL fallback: inferred terminal for %d blank-terminal rows", n_filled)
    return out


def filter_eligible(df: pd.DataFrame, rules, today: date | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply Section 2 eligibility filters. Returns (eligible, excluded).

    ``excluded`` carries an added ``exclusion_reason`` column naming the first
    failed filter, for audit/the Suggested-Removals style review.

    Args:
        df: normalized per-container frame.
        rules: a :class:`PortRules` instance.
        today: reference date for the past-ETA filter (defaults to date.today()).
    """
    if today is None:
        today = date.today()
    work = df.copy()
    work["exclusion_reason"] = pd.NA

    def _flag(mask: pd.Series, reason: str):
        # Only set a reason for rows not already excluded (first reason wins).
        newly = mask & work["exclusion_reason"].isna()
        work.loc[newly, "exclusion_reason"] = reason

    # 2.1 Priority — exclude any priority containing an excluded token.
    if "priority_code" in work.columns:
        for token in rules.excluded_priorities:
            _flag(_contains_any(work["priority_code"], [token]), f"Priority contains '{token}'")

    # 2.2 Category — exclude Robotics / Devices.
    if "category" in work.columns:
        _flag(_contains_any(work["category"], rules.excluded_categories),
              "Excluded category (Robotics/Devices)")

    # 2.3 Destination exclusion list (substring match on facility).
    if "facility" in work.columns and rules.excluded_destinations:
        _flag(_contains_any(work["facility"], rules.excluded_destinations),
              "Excluded destination")

    # 2.4 Secondary destinations are excluded from the PRIMARY pool. They are
    # tagged (not dropped) so Phase 2 can pull them back in if below target.
    work["is_secondary_destination"] = False
    if "facility" in work.columns and rules.secondary_destinations:
        sec_mask = _contains_any(work["facility"], rules.secondary_destinations)
        work["is_secondary_destination"] = sec_mask
        _flag(sec_mask, "Secondary destination (Phase 2 only)")

    # 2.5 Vessel — exclude AIR FREIGHT.
    if "vessel" in work.columns and rules.excluded_vessels:
        _flag(_contains_any(work["vessel"], rules.excluded_vessels), "Excluded vessel")

    # 2.6 Carrier — exclude DNSL.
    if "scac" in work.columns and rules.excluded_carriers:
        _flag(_contains_any(work["scac"], rules.excluded_carriers), "Excluded carrier (DNSL)")

    # 2.7 Ocean ETA required + not in the past.
    if rules.require_ocean_eta:
        eta = pd.to_datetime(work.get("ocean_eta"), errors="coerce")
        work["ocean_eta"] = eta
        missing = eta.isna()
        _flag(missing, "Missing Ocean ETA")
        # Compare against a normalized Timestamp (not date) so an all-NaT column
        # doesn't raise on a datetime64-vs-date comparison.
        today_ts = pd.Timestamp(today).normalize()
        past = eta.notna() & (eta.dt.normalize() < today_ts)
        _flag(past, "Ocean ETA in the past")

    excluded = work[work["exclusion_reason"].notna()].copy()
    # Eligible = not excluded for a HARD reason. Secondary-destination rows are
    # "excluded" from primary but remain available to Phase 2, so they stay in
    # the eligible frame flagged via is_secondary_destination.
    hard_excluded = work["exclusion_reason"].notna() & (
        work["exclusion_reason"] != "Secondary destination (Phase 2 only)"
    )
    eligible = work[~hard_excluded].copy()
    # Clear the soft reason on rows that survive into the eligible pool.
    eligible.loc[
        eligible["exclusion_reason"] == "Secondary destination (Phase 2 only)",
        "exclusion_reason",
    ] = pd.NA

    logger.info(
        "Eligibility: %d in -> %d eligible (%d secondary), %d hard-excluded",
        len(df), len(eligible), int(eligible["is_secondary_destination"].sum()),
        int(hard_excluded.sum()),
    )
    return eligible, excluded


def missing_field_rate(df: pd.DataFrame) -> float:
    """Section 10 trigger input: fraction of rows missing any critical field."""
    if df.empty:
        return 0.0
    present = [c for c in CRITICAL_FIELDS if c in df.columns]
    if not present:
        return 1.0
    missing_any = pd.Series(False, index=df.index)
    for c in present:
        col = df[c]
        blank = col.isna() | (col.astype(str).str.strip().isin(["", "nan", "NaT"]))
        missing_any |= blank
    return float(missing_any.mean())
