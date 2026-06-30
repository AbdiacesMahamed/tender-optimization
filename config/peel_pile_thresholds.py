"""Per-port (and per-terminal) peel-pile qualifying thresholds.

A "peel pile" is a Vessel/Week/Port/Terminal group large enough that the
business wants to single it out for manual carrier allocation. The *qualifying
threshold* is the minimum container count a group must reach to show up in the
Peel Pile Analysis table. Historically this was a single hardcoded ``30`` for
every port; this module makes it port- and terminal-specific.

Single source of truth
-----------------------
``components/constraints/peel_pile.py`` reads the threshold for each group row
through :func:`peel_pile_threshold` — no thresholds live in that file anymore.
To change the rules, edit the tables below; no engine code changes are needed.

The rules (as specified by the business)
-----------------------------------------
* **PNW** — the Pacific-Northwest ports, discharged-port codes ``TIW`` (Tacoma)
  and ``SEA`` (Seattle). Each terminal carries its own limit; anything without
  a specific limit falls back to the PNW port default of ``80``. The per-terminal
  limits are keyed by the EXACT ``Terminal`` string GVT emits (verified against
  the PNW GVT extract and Amazon's Dray Operations terminal registry):

    ===================  ====================================  =====
    GVT ``Terminal``     Terminal                              Limit
    ===================  ====================================  =====
    ``TRM-TWUT``         Washington United Terminal (WUT)        40
    ``TRM-T004``         Husky Terminal (Tacoma Terminal 4)      45
    ``SSA-T18``          Terminal 18 (Seattle)                   30
    ``TERMINAL 5``       Terminal 5 (Seattle)                    30
    ``TRM-TPCT``         Pierce County Terminal (PCT)            80 (port default)
    (blank / other)      —                                      80 (port default)
    ===================  ====================================  =====

* **OAK** — Oakland keeps the original ``30`` threshold.

* **Every other port** — peel-pile detection is effectively OFF: the threshold is
  a sentinel so large that no real group ever qualifies. The "30 rule" is
  therefore OAK-only, and the per-terminal limits are PNW-only, exactly as asked.

This module is stdlib-only so the Streamlit-free layers can share it.
"""
from __future__ import annotations

from typing import Optional

# A group can never realistically reach this, so a port mapped here shows no
# peel piles. Used for every port not explicitly listed below.
DISABLED_THRESHOLD = 10**9

# Discharged-port codes that make up the Pacific Northwest.
PNW_PORTS = {"TIW", "SEA"}

# PNW fallback when a terminal has no specific limit (incl. PCT and blanks).
PNW_DEFAULT_THRESHOLD = 80

# Per-terminal PNW limits, keyed by the EXACT GVT ``Terminal`` string,
# uppercased for case-insensitive lookup.
PNW_TERMINAL_THRESHOLDS = {
    "TRM-TWUT": 40,     # Washington United Terminal (WUT)
    "TRM-T004": 45,     # Husky Terminal (Tacoma Terminal 4)
    "SSA-T18": 30,      # Terminal 18 (Seattle)
    "TERMINAL 5": 30,   # Terminal 5 (Seattle)
    # TRM-TPCT (Pierce County) and any other/blank terminal fall back to 80.
}

# Non-PNW ports that keep an explicit peel-pile threshold. Everything absent
# from both this map and PNW_PORTS is disabled (DISABLED_THRESHOLD).
PORT_THRESHOLDS = {
    "OAK": 30,
}


def peel_pile_threshold(port, terminal=None) -> int:
    """Minimum container count for a group at ``port``/``terminal`` to qualify.

    Case- and whitespace-insensitive on both arguments. Resolution order:

    1. A PNW port (``TIW``/``SEA``): use the per-terminal limit if one exists,
       else the PNW port default (80).
    2. A port listed in :data:`PORT_THRESHOLDS` (e.g. OAK -> 30).
    3. Anything else: :data:`DISABLED_THRESHOLD` (peel piles effectively off).

    Examples::

        peel_pile_threshold("TIW", "TRM-TWUT")   -> 40
        peel_pile_threshold("TIW", "TRM-T004")   -> 45
        peel_pile_threshold("SEA", "Terminal 5") -> 30
        peel_pile_threshold("TIW", "TRM-TPCT")   -> 80   (PNW default)
        peel_pile_threshold("TIW", None)         -> 80   (PNW default)
        peel_pile_threshold("OAK")               -> 30
        peel_pile_threshold("LAX")               -> 10**9 (disabled)
    """
    port_key = "" if port is None else str(port).strip().upper()

    if port_key in PNW_PORTS:
        term_key = "" if terminal is None else str(terminal).strip().upper()
        if term_key in PNW_TERMINAL_THRESHOLDS:
            return PNW_TERMINAL_THRESHOLDS[term_key]
        return PNW_DEFAULT_THRESHOLD

    if port_key in PORT_THRESHOLDS:
        return PORT_THRESHOLDS[port_key]

    return DISABLED_THRESHOLD


def min_threshold() -> int:
    """Smallest threshold any port can use — the cheapest pre-filter bound.

    Lets a caller drop obviously-too-small groups in one vectorized pass before
    applying the precise per-row threshold. Equals the smallest configured limit
    (currently 30); never returns the disabled sentinel.
    """
    candidates = [PNW_DEFAULT_THRESHOLD, *PNW_TERMINAL_THRESHOLDS.values(),
                  *PORT_THRESHOLDS.values()]
    return min(candidates) if candidates else DISABLED_THRESHOLD
