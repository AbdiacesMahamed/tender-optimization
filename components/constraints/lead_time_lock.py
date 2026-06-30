"""Lead-time allocation lock — freeze carriers within 3 days of Ocean ETA.

Standing rule: **once a container is within 3 days of its vessel arrival (Ocean
ETA), its carrier can no longer be changed.** There is no time left to re-tender
a move that close to arrival, so the container must ship on whoever it is already
assigned to in the GVT data.

"Day minus 3": the allocation deadline is ``Ocean ETA - 3 days``. Once today has
passed that deadline — i.e. fewer than 3 full days of lead time remain
(``Ocean ETA - 3 < today``) — the row is locked. Containers arriving today, or
already past, are therefore always locked; a container 4+ days out stays free.

Mechanism (not exclusion — the volume stays in the analysis): a locked row is
moved from the scenario-eligible (``unconstrained``) pool into the frozen
(``constrained``) pool. The dashboard already guarantees that nothing in the
constrained pool is touched by the Optimized / Performance / Cheapest scenarios,
so moving a row there is exactly "keep this container on its current carrier, do
not flip it". Volume is conserved: every row removed from one frame is added to
the other.

Pure pandas over the dashboard's per-group frames — no Streamlit, no session
state — so it is unit-testable in isolation. Inputs are copied before mutation.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

#: Days of lead time required before Ocean ETA for an allocation/flip to be allowed.
LEAD_TIME_DAYS = 3

ETA_COL = "Ocean ETA"


def lead_time_lock_mask(df: pd.DataFrame, today: date | None = None) -> pd.Series:
    """Boolean mask of rows locked by the lead-time rule (``ETA - 3 < today``).

    A row is locked when its Ocean ETA is within ``LEAD_TIME_DAYS`` of ``today``
    (including today and any past-dated ETA). Rows with no parseable Ocean ETA are
    NOT locked — we can't prove they're inside the window, so they stay eligible
    (matching how the rest of the pipeline treats un-dated rows). Returns an
    all-False mask when the frame is empty or has no Ocean ETA column.
    """
    if df is None or len(df) == 0 or ETA_COL not in df.columns:
        return pd.Series([False] * (0 if df is None else len(df)),
                         index=None if df is None else df.index, dtype=bool)

    if today is None:
        today = date.today()
    today_ts = pd.Timestamp(today).normalize()
    deadline = today_ts  # row is locked when (ETA - LEAD_TIME_DAYS) < today

    eta = pd.to_datetime(df[ETA_COL], errors="coerce").dt.normalize()
    # (ETA - LEAD_TIME_DAYS) < today  <=>  ETA < today + LEAD_TIME_DAYS
    cutoff = deadline + pd.Timedelta(days=LEAD_TIME_DAYS)
    return eta.notna() & (eta < cutoff)


def apply_lead_time_lock(constrained: pd.DataFrame,
                         unconstrained: pd.DataFrame,
                         today: date | None = None):
    """Freeze within-window rows: move them from unconstrained → constrained.

    Returns ``(constrained, unconstrained, locked_count)``. Rows whose Ocean ETA
    is within ``LEAD_TIME_DAYS`` of ``today`` are pulled out of the scenario-
    eligible (``unconstrained``) pool and appended to the frozen (``constrained``)
    pool so no scenario can flip their carrier. Volume is conserved. Rows already
    in the constrained pool are left as-is (they're frozen regardless of date).

    Both inputs are copied before mutation; callers get new frames back. A None
    pool is treated as empty.
    """
    c = constrained.copy() if constrained is not None else pd.DataFrame()
    u = unconstrained.copy() if unconstrained is not None else pd.DataFrame()

    if len(u) == 0 or ETA_COL not in u.columns:
        return c, u, 0

    mask = lead_time_lock_mask(u, today=today)
    if not mask.any():
        return c, u, 0

    to_lock = u[mask]
    locked_count = int(pd.to_numeric(
        to_lock.get("Container Count"), errors="coerce"
    ).fillna(0).sum()) if "Container Count" in to_lock.columns else int(mask.sum())

    remaining = u[~mask]
    # Append the frozen rows to the constrained pool. Align on the union of columns
    # so a missing column on either side becomes NaN rather than raising.
    if len(c) == 0:
        new_c = to_lock.copy()
    else:
        new_c = pd.concat([c, to_lock], ignore_index=True)

    return new_c.reset_index(drop=True), remaining.reset_index(drop=True), locked_count
