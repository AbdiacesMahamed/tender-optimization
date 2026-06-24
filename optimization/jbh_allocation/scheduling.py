"""Lead times, expected-outgate dates, and week numbering for the JBH model.

Implements Section 3 (lead time configuration + expected outgate priority +
vessel discharge tiering), Section 13 (weekend / terminal-specific day shifts),
and Section 14 (VBA-compatible week numbering). Pure pandas/stdlib.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


def vba_week_number(d: date) -> int:
    """Section 14: VBA Format(date, "ww", vbSunday, vbFirstJan1) week number.

    Rules:
      * Weeks start on Sunday.
      * January 1 is always in week 1.
    Week N = number of Sunday-started weeks since the Sunday on/before Jan 1.

    Implementation: find Jan 1's week-start Sunday (the Sunday on or before
    Jan 1), then count how many 7-day blocks d is past it, +1.
    """
    if d is None or pd.isna(d):
        return None
    if not isinstance(d, date) or isinstance(d, datetime):
        d = pd.Timestamp(d).date()

    jan1 = date(d.year, 1, 1)
    # Python weekday(): Mon=0..Sun=6. Days since the most recent Sunday:
    days_since_sunday_jan1 = (jan1.weekday() + 1) % 7  # Sun->0, Mon->1, ... Sat->6
    week1_start = jan1 - timedelta(days=days_since_sunday_jan1)
    delta_days = (d - week1_start).days
    return delta_days // 7 + 1


def _shift_weekend(d: date, shift_saturday: bool, shift_sunday: bool) -> date:
    """Section 13: shift Saturday/Sunday forward to Monday per the flags."""
    wd = d.weekday()  # Mon=0..Sun=6
    if wd == 5 and shift_saturday:   # Saturday
        return d + timedelta(days=2)
    if wd == 6 and shift_sunday:     # Sunday
        return d + timedelta(days=1)
    return d


def compute_expected_outgate(df: pd.DataFrame, rules) -> pd.DataFrame:
    """Section 3.3: compute 'expected_outgate' using the BEST available date.

    Priority:
      1. If term_avail exists: expected_outgate = term_avail + AV lead time.
      2. Else: expected_outgate = ocean_eta + terminal ETA lead time.
    Then apply:
      * APM Friday-ETA +1 discharge delay (3.3 / 13.2), based on the ETA weekday.
      * Weekend shift (Section 13), per-terminal.
    Adds 'expected_outgate' (datetime) and 'expected_outgate_week' (VBA week).
    Returns a copy. Rows whose dates can't be computed get NaT.
    """
    out = df.copy()
    eta = pd.to_datetime(out.get("ocean_eta"), errors="coerce")
    avail = pd.to_datetime(out.get("term_avail"), errors="coerce") if "term_avail" in out.columns else pd.Series(pd.NaT, index=out.index)

    terminals = out["terminal"].astype(str).str.strip().str.upper() if "terminal" in out.columns else pd.Series("", index=out.index)

    def _row_outgate(i):
        term = terminals.iloc[out.index.get_loc(i)] if "terminal" in out.columns else ""
        a = avail.loc[i] if i in avail.index else pd.NaT
        e = eta.loc[i] if i in eta.index else pd.NaT

        if pd.notna(a):
            base = a.date() + timedelta(days=rules.terminal_av_lead(term))
        elif pd.notna(e):
            lead = rules.terminal_eta_lead(term)
            # 3.3 / 13.2 Friday ETA discharge delay (e.g. APM +1).
            fri_offset = rules.terminal_friday_eta_offset.get(term, 0)
            if e.weekday() == 4 and fri_offset:  # Friday
                lead += fri_offset
            base = e.date() + timedelta(days=lead)
        else:
            return pd.NaT

        shift_sat, shift_sun = rules.weekend_shift(term)
        adjusted = _shift_weekend(base, shift_sat, shift_sun)
        return pd.Timestamp(adjusted)

    out["expected_outgate"] = [_row_outgate(i) for i in out.index]
    out["expected_outgate_week"] = out["expected_outgate"].apply(
        lambda x: vba_week_number(x.date()) if pd.notna(x) else None
    )
    return out


def apply_vessel_tiering(df: pd.DataFrame, rules) -> pd.DataFrame:
    """Section 3.4: vessels with >= threshold containers get a +offset day.

    Adds 'vessel_container_count' and bumps 'expected_outgate' by the offset for
    rows on high-volume vessels. Must run AFTER compute_expected_outgate.
    Returns a copy.
    """
    out = df.copy()
    if "vessel" not in out.columns or "expected_outgate" not in out.columns:
        out["vessel_container_count"] = 0
        return out

    counts = out.groupby(out["vessel"].astype(str).str.strip())["container_id"].transform("count") \
        if "container_id" in out.columns else out.groupby(out["vessel"].astype(str).str.strip())["vessel"].transform("count")
    out["vessel_container_count"] = counts

    high = counts >= rules.vessel_tier_threshold
    offset = pd.to_timedelta(rules.vessel_tier_offset_days, unit="D")
    out.loc[high & out["expected_outgate"].notna(), "expected_outgate"] = (
        out.loc[high & out["expected_outgate"].notna(), "expected_outgate"] + offset
    )
    # Recompute week after the bump.
    out["expected_outgate_week"] = out["expected_outgate"].apply(
        lambda x: vba_week_number(x.date()) if pd.notna(x) else None
    )
    n_high = int(high.sum())
    if n_high:
        logger.info("Vessel tiering: +%dd applied to %d containers on high-volume vessels",
                    rules.vessel_tier_offset_days, n_high)
    return out
