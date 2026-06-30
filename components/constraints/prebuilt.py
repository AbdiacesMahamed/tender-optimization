"""Prebuilt, per-port operational constraints that ship with the app.

These are the "always-on" constraint rows the business wants enforced on every
run, independent of whatever a user uploads or asks the assistant for. They live
as one CSV per port under ``config/port_constraints/`` (e.g. ``LAX.csv``), each
using the SAME 14-column schema as an uploaded constraints file, so they are
easy to read and edit in Excel or any text editor.

Two guarantees, both required by the business:

1. **Prebuilt rules cannot be overwritten by user constraints.** They are merged
   to the FRONT of the constraint frame (see :func:`merge_prebuilt_first`).
   ``apply_constraints_to_data`` processes rows in order and the first matching
   rule claims its containers first, so a prebuilt rule always wins — *even if an
   uploaded/chatbot rule carries a higher Priority Score*. Priority Score only
   orders rules WITHIN the prebuilt block and WITHIN the user block; it never
   lets a user rule jump ahead of a prebuilt one.

2. **On/off is controlled in code only — never exposed in the UI.** Flip the
   switches in :data:`ENABLED` / :data:`PREBUILT_CONSTRAINTS_ENABLED` below. The
   user only ever sees the outcome (a confirmation that their constraints, plus
   the standing port rules, were applied) — not these toggles.

To EDIT the rules: open the relevant ``config/port_constraints/<PORT>.csv`` and
add/change rows. A header-only file (no data rows) is a no-op for that port.
To ADD a port: drop in a ``<PORT>.csv`` and add its code to :data:`ENABLED`.
"""
from __future__ import annotations

import os
import pandas as pd

from ..core.utils import parse_day_of_week
from .processor import expected_constraint_columns

# ---------------------------------------------------------------------------
# IN-CODE TOGGLES (engineers only — not surfaced in the UI)
# ---------------------------------------------------------------------------

# Master switch. Set to False to disable ALL prebuilt port constraints at once.
PREBUILT_CONSTRAINTS_ENABLED = True

# Per-port switches. A port whose CSV exists but is set to False here is skipped;
# a port set to True with a header-only CSV simply contributes no rows. Keyed by
# the uppercase Discharged Port code (the same convention used everywhere else).
ENABLED: dict[str, bool] = {
    "LAX": True,
    "NYC": True,
    "BAL": True,
    "NFK": True,
    "CHI": True,
    "MKC": True,
    "MEM": True,
    # PNW waterfront — carrier-to-port lockouts. SEA = Seattle, TIW = Tacoma.
    # Waterfront (AOYV) and RoadEx (RDXY) run Seattle only (locked out of TIW);
    # RoadOne (RKNE) and JB Hunt (HJBT) run Tacoma only (locked out of SEA).
    "SEA": True,
    "TIW": True,
}

# Directory holding one CSV per port.
_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config",
    "port_constraints",
)

# Marker column added to prebuilt rows so downstream code / summaries can tell
# them apart from user-supplied rows. Carried through apply_constraints_to_data
# harmlessly (it is not one of the scope/amount fields it reads).
SOURCE_COLUMN = "Constraint Source"


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce a raw per-port CSV into the canonical constraint schema.

    Mirrors the cleaning ``process_constraints_file`` applies to uploaded Excel
    files (numeric coercion, percent decimal→whole, day-of-week parsing, blank→
    None) but stays silent (no Streamlit messages) since this runs unattended.
    """
    df = df.copy()
    df.columns = df.columns.str.strip()

    for col in expected_constraint_columns():
        if col not in df.columns:
            df[col] = None

    text_cols = ["Category", "Lane", "Carrier", "Port", "Terminal",
                 "Excluded FC", "SSL", "Vessel"]
    for col in text_cols:
        df[col] = df[col].apply(
            lambda x: None if pd.isna(x) or (isinstance(x, str) and x.strip() == "") else x
        )

    df["Week Number"] = pd.to_numeric(df["Week Number"], errors="coerce")
    df["Day of Week"] = df["Day of Week"].apply(parse_day_of_week)

    def _clean_percent(val):
        if pd.isna(val) or val == "":
            return None
        if isinstance(val, (int, float)):
            return val * 100 if 0 < val <= 1 else val
        val_str = str(val).strip().replace("%", "")
        try:
            num = float(val_str)
            return num * 100 if 0 < num <= 1 else num
        except ValueError:
            return None

    df["Percent Allocation"] = df["Percent Allocation"].apply(_clean_percent)
    df["Maximum Container Count"] = pd.to_numeric(df["Maximum Container Count"], errors="coerce")
    df["Minimum Container Count"] = pd.to_numeric(df["Minimum Container Count"], errors="coerce")
    df["Priority Score"] = pd.to_numeric(df["Priority Score"], errors="coerce")

    # Keep only rows that carry a Priority Score (matches uploaded-file behavior).
    df = df[df["Priority Score"].notna()]
    return df


def load_prebuilt_constraints() -> pd.DataFrame:
    """Return all enabled prebuilt port constraints as one constraint frame.

    Sorted by Priority Score (desc) so higher-priority prebuilt rules process
    first WITHIN the prebuilt block. Returns an empty DataFrame (with the right
    columns) when the master switch is off or no rules are defined.
    """
    cols = expected_constraint_columns() + [SOURCE_COLUMN]
    if not PREBUILT_CONSTRAINTS_ENABLED:
        return pd.DataFrame(columns=cols)

    frames = []
    for port, on in ENABLED.items():
        if not on:
            continue
        path = os.path.join(_DIR, f"{port}.csv")
        if not os.path.exists(path):
            continue
        try:
            raw = pd.read_csv(path)
        except pd.errors.EmptyDataError:
            continue
        except Exception:
            continue
        if raw.empty:
            continue
        norm = _normalize_frame(raw)
        if norm.empty:
            continue
        norm[SOURCE_COLUMN] = f"Prebuilt:{port}"
        frames.append(norm)

    if not frames:
        return pd.DataFrame(columns=cols)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("Priority Score", ascending=False, na_position="last")
    return combined.reset_index(drop=True)


def load_pnw_generated_constraints(data: pd.DataFrame | None) -> pd.DataFrame:
    """Return data-derived PNW vessel rules (Rule 1 + Rule 2) as a constraint frame.

    Unlike the static per-port CSVs, these rules depend on the loaded GVT data
    (the weeks present at Tacoma for the Hunt 130/week rule, and the
    (vessel, carrier) pairs at PNW ports for the 60-per-vessel cap), so they are
    generated on the fly from ``data``. Returns an empty (correctly-columned)
    frame when the master switch is off, ``data`` is None/empty, or no PNW rows
    are present. Tagged with SOURCE_COLUMN = "Prebuilt:PNW" so they read as
    always-on standing rules alongside the per-port lockouts.
    """
    cols = expected_constraint_columns() + [SOURCE_COLUMN]
    if not PREBUILT_CONSTRAINTS_ENABLED or data is None or len(data) == 0:
        return pd.DataFrame(columns=cols)
    # Imported lazily to avoid a circular import at module load (pnw_vessel_rules
    # imports from .processor, which this package also wires together).
    from .pnw_vessel_rules import build_pnw_constraint_rows
    rows = build_pnw_constraint_rows(data)
    if rows is None or len(rows) == 0:
        return pd.DataFrame(columns=cols)
    rows = rows.copy()
    rows[SOURCE_COLUMN] = "Prebuilt:PNW"
    return rows.reset_index(drop=True)


def merge_prebuilt_first(
    user_constraints_df: pd.DataFrame | None,
    data: pd.DataFrame | None = None,
) -> pd.DataFrame | None:
    """Prepend enabled prebuilt rules so they are applied BEFORE user rules.

    The result is intentionally NOT re-sorted by Priority Score: prebuilt rows
    stay at the front, which is what makes them un-overridable by a user rule's
    Priority Score. Each block (prebuilt, user) is internally priority-ordered by
    its own loader. Returns the user frame unchanged when no prebuilt rules apply,
    or just the prebuilt frame when the user supplied none.

    When ``data`` is supplied, the data-derived PNW vessel rules (Rule 1: Hunt
    exactly 130/week at TIW; Rule 2: no SCAC over 60/vessel) are generated from it
    and merged into the front block too, right after the static per-port lockouts.
    """
    static_prebuilt = load_prebuilt_constraints()
    pnw_generated = load_pnw_generated_constraints(data)
    prebuilt_frames = [f for f in (static_prebuilt, pnw_generated) if len(f) > 0]
    prebuilt = (pd.concat(prebuilt_frames, ignore_index=True)
                if prebuilt_frames else static_prebuilt)

    if user_constraints_df is not None and len(user_constraints_df) > 0:
        user = user_constraints_df.copy()
        if SOURCE_COLUMN not in user.columns:
            user[SOURCE_COLUMN] = "User"
        else:
            user[SOURCE_COLUMN] = user[SOURCE_COLUMN].fillna("User")
    else:
        user = None

    if len(prebuilt) == 0:
        return user

    if user is None:
        return prebuilt

    return pd.concat([prebuilt, user], ignore_index=True)
