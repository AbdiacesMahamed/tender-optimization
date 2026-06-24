"""Port-keyed configuration for the JBH (JB Hunt) Allocation Model.

This module is the SINGLE SOURCE OF TRUTH for every port-specific rule in the
allocation model described in ``Allocation_Model_Rules_Reference.docx``. The
engine in ``optimization/jbh_allocation/`` reads everything from here, so:

    ➤ Adding a new port = adding ONE entry to ``PORT_ALLOCATION_RULES`` below.
      No engine code changes are required.

The first (and currently only) entry, ``LAX``, encodes the rules exactly as the
reference document specifies. To add another port, copy the ``LAX`` block,
rename the key, and edit the values for that port's terminals, lead times,
splits, caps, and exclusion lists. Anything you omit falls back to the shared
defaults in ``DEFAULT_RULES`` (see :func:`get_port_rules`), so a minimal new
port only needs to override what actually differs.

Design notes
------------
* All values are plain Python literals (dicts/lists/ints) — no logic — so the
  file stays reviewable and editable by non-engineers.
* ``PortRules`` is a thin dataclass wrapper that gives the engine attribute
  access (``rules.weekly_target``) and merges a port's overrides over the
  defaults. The raw dicts remain the editable surface.
* Day names are lowercase strings ('monday'..'sunday') everywhere.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


# ===========================================================================
# Shared defaults — apply to every port unless the port overrides them.
# These mirror the "Default" rows and global rules in the reference document.
# ===========================================================================

DEFAULT_RULES: dict[str, Any] = {
    # ---- Section 2: eligibility filters (global lists) ----
    "excluded_priorities": ["Express"],          # 2.1 / 12.5 — substring, case-insensitive
    "excluded_categories": ["Robotics", "Devices"],  # 2.2 / 12.4
    "excluded_vessels": ["AIR FREIGHT"],         # 2.5 / 12.2
    "excluded_carriers": ["DNSL"],               # 2.6 / 12.3
    "require_ocean_eta": True,                    # 2.7 — drop null/blank/past ETA
    # Destination exclusions are port-specific (different FCs per port) — see LAX.
    "excluded_destinations": [],                  # 2.3 / 12.1
    "secondary_destinations": [],                 # 2.4 / 11.2 — included only in Phase 2

    # ---- Section 3: lead times (days) ----
    "default_eta_lead_time": 4,                   # 3.1 "Default (any other)"
    "default_av_lead_time": 3,                    # 3.2 "Default"
    "eta_lead_times": {},                         # terminal -> days (3.1)
    "av_lead_times": {},                          # terminal -> days (3.2)
    # 3.4 vessel discharge tiering
    "vessel_tier_threshold": 100,                 # vessels with >= N containers
    "vessel_tier_offset_days": 1,                 # get +1 day on expected outgate

    # ---- Section 4: targets & capacity ----
    "base_weekly_target": 275,                    # 4.1
    "weekly_cap_multiplier": 1.15,                # 4.1 -> weekly cap = target * 1.15 (316)
    "hard_weekly_ceiling": 345,                   # 4.1
    "containers_per_shift_tl": 1.4,               # 4.1 dynamic calc: TL fraction weight
    "containers_per_shift_cd": 1.0,               # 4.1 dynamic calc: CD fraction weight
    "shifts_per_week": 250,                       # 4.1 dynamic calc multiplier
    "daily_caps": {                               # 4.2 day -> max outgates
        "monday": 65, "tuesday": 65, "wednesday": 65,
        "thursday": 65, "friday": 65, "saturday": 25, "sunday": 0,
    },
    "daily_drivers_available": 50,                # 4.2
    "soft_day_cap_pct": 0.35,                     # 4.3 passes 1-4
    "hard_day_cap_pct": 0.45,                     # 4.3 pass 5

    # ---- Section 5: terminal split ----
    # strategy_terminals: terminal -> {"base_pct", "buffer_pct"} (5.1)
    "strategy_terminals": {},
    "backup_terminals": [],                       # 5.2 priority order
    "backup_buffer_pct": 0.25,                    # 5.2

    # ---- Section 7 / 11: HJBT concentration & preferred facilities ----
    "primary_carrier": "HJBT",                    # the carrier the model concentrates on
    "hjbt_max_concentration": 0.80,               # 7 — flag excess above this share
    "hjbt_floor_pct": 0.65,                       # 6.1 / 7 — floor per terminal cap
    "preferred_facilities": [],                   # 11.1 — Pass 1 / Pass 3 priority

    # ---- Section 8: horizon ----
    "horizon_weeks": 4,                           # current + next 3
    "core_horizon_weeks": 3,                       # weeks +0..+2 get full logic
    # extended week (+3) = horizon_weeks - 1 index, restricted logic

    # ---- Section 9: rollover ----
    "rollover_cap_pct": 0.30,                     # of hard weekly ceiling

    # ---- Section 13: weekend / day-shift adjustments ----
    # default: both Saturday and Sunday shift to Monday.
    # Per-terminal overrides (e.g. APM/TTI shift Sunday only) live in
    # "terminal_weekend_rules": terminal -> {"shift_saturday": bool, "shift_sunday": bool}
    "shift_saturday_default": True,
    "shift_sunday_default": True,
    "terminal_weekend_rules": {},
    # 3.3 / 13.2 APM Friday ETA discharge delay: terminal -> +days when ETA is Friday
    "terminal_friday_eta_offset": {},

    # ---- Section 10: trigger thresholds ----
    "triggers": {
        "accuracy_floor": 0.70,                   # warn if weekly accuracy < 70%
        "average_error_max_days": 1.5,            # warn if avg day error > 1.5
        "miss_rate_shift_max": 0.05,              # warn if WoW miss rate +>5pts
        "day_concentration_max": 0.35,            # warn if a day > 35% of week
        "weekly_cap": 316,                        # warn if week total > 316
        "target_floor_pct": 0.90,                 # warn if < 90% of base target
        "rolling_accuracy_floor": 0.65,           # warn if rolling 4wk < 65%
        "hjbt_concentration_max": 0.80,           # warn if HJBT share > 80%
        "missing_field_rate_max": 0.05,           # warn if >5% missing critical fields
    },

    # ---- Section 15: SSL -> terminal fallback ----
    "ssl_fallback_default_terminal": None,        # used when SSL unknown; LAX -> APM
}


# ===========================================================================
# Port-specific rules. ADD NEW PORTS HERE.
# Keys are uppercase port codes matching the GVT 'Discharged Port' convention
# (e.g. 'LAX', 'BAL', 'NYC'). Only the fields that differ from DEFAULT_RULES
# need to be listed; everything else is inherited.
# ===========================================================================

PORT_ALLOCATION_RULES: dict[str, dict[str, Any]] = {
    # -------------------------------------------------------------------
    # LAX — Los Angeles / Long Beach. Encodes the reference doc verbatim.
    # -------------------------------------------------------------------
    "LAX": {
        # 2.3 / 12.1 excluded destinations (substring, case-insensitive)
        "excluded_destinations": [
            "DEN2", "DEN5", "DFW6", "FTW6", "HOU2", "HOU8", "OKC1",
            "SAT1", "SAT2", "SLC1", "TUS2", "IUS", "APXLCARAN", "IUTE",
            "GEU", "ISUQ", "AMZ-LGB", "VG2-IXD", "LAS1-IXD", "XLX7",
            "PSP3", "LAS1", "VGT2", "QXY",
        ],
        # 2.4 / 11.2 secondary destinations (Phase 2 only)
        "secondary_destinations": ["LAX9-S", "LGB4-NS", "LGB8-S"],

        # 3.1 Ocean ETA -> expected outgate lead times by terminal
        "eta_lead_times": {
            "APM": 3, "TTI": 3, "TRAPAC": 2, "PCT": 6, "FMS": 2,
            "WBCT": 4, "ITS": 5, "YTI": 4, "LBCT-E": 4, "ETS": 4,
        },
        # 3.2 Terminal Available -> expected outgate lead times by terminal
        "av_lead_times": {
            "APM": 2, "TTI": 2, "TRAPAC": 3, "FMS": 3, "YTI": 2,
            "WBCT": 3, "PCT": 3, "ITS": 3,
        },

        # 5.1 strategy terminals
        "strategy_terminals": {
            "APM": {"base_pct": 0.70, "buffer_pct": 0.15},
            "TTI": {"base_pct": 0.20, "buffer_pct": 0.25},
            "TRAPAC": {"base_pct": 0.10, "buffer_pct": 0.20},
        },
        # 5.2 backup terminals (priority order) — 25% buffer (default)
        "backup_terminals": ["PCT", "YTI", "ITS", "WBCT", "FMS"],

        # 11.1 preferred facilities (TL, Pass 1 / Pass 3 priority)
        "preferred_facilities": ["XLA4", "DDSI-SFS"],
        # 4.1 preferred-facility weekly target range
        "preferred_facility_target_range": (120, 135),

        # 13.2 / 13.3 APM and TTI shift Sunday only (Saturday stays)
        "terminal_weekend_rules": {
            "APM": {"shift_saturday": False, "shift_sunday": True},
            "TTI": {"shift_saturday": False, "shift_sunday": True},
        },
        # 3.3 / 13.2 APM Friday ETA +1 day discharge delay
        "terminal_friday_eta_offset": {"APM": 1},

        # 15 SSL fallback default terminal
        "ssl_fallback_default_terminal": "APM",
    },
}


# ===========================================================================
# Access layer — merges a port's overrides over the shared defaults and
# exposes the result as an attribute-friendly object for the engine.
# ===========================================================================

@dataclass
class PortRules:
    """Resolved, merged rule set for a single port.

    Built by :func:`get_port_rules`. Attribute names mirror the keys in
    ``DEFAULT_RULES``. ``raw`` keeps the full merged dict for any keys not
    promoted to attributes (e.g. ``preferred_facility_target_range``).
    """

    port: str
    raw: dict[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        # Falls through to merged-dict keys not declared as dataclass fields.
        try:
            return self.raw[name]
        except KeyError as exc:
            raise AttributeError(
                f"No allocation rule '{name}' for port '{self.port}'. "
                f"Add it to DEFAULT_RULES or the port entry in "
                f"config/port_allocation_rules.py."
            ) from exc

    def get(self, name: str, default: Any = None) -> Any:
        return self.raw.get(name, default)

    # ---- convenience derived values (computed from the raw rules) ----

    def weekly_cap(self, target: int) -> int:
        """4.1 weekly cap (trigger threshold) = int(target * multiplier)."""
        return int(target * self.raw["weekly_cap_multiplier"])

    def soft_day_cap(self, target: int) -> int:
        """4.3 soft day cap = floor(target * soft_day_cap_pct)."""
        return int(target * self.raw["soft_day_cap_pct"])

    def hard_day_cap(self, target: int) -> int:
        """4.3 hard day cap = floor(target * hard_day_cap_pct)."""
        return int(target * self.raw["hard_day_cap_pct"])

    def rollover_cap(self) -> int:
        """9 rollover cap = floor(hard_weekly_ceiling * rollover_cap_pct)."""
        return int(self.raw["hard_weekly_ceiling"] * self.raw["rollover_cap_pct"])

    def terminal_eta_lead(self, terminal: str) -> int:
        """3.1 ETA lead time for a terminal, falling back to the default."""
        return self.raw["eta_lead_times"].get(terminal, self.raw["default_eta_lead_time"])

    def terminal_av_lead(self, terminal: str) -> int:
        """3.2 AV lead time for a terminal, falling back to the default."""
        return self.raw["av_lead_times"].get(terminal, self.raw["default_av_lead_time"])

    def weekend_shift(self, terminal: str) -> tuple[bool, bool]:
        """13 (shift_saturday, shift_sunday) for a terminal."""
        override = self.raw["terminal_weekend_rules"].get(terminal, {})
        return (
            override.get("shift_saturday", self.raw["shift_saturday_default"]),
            override.get("shift_sunday", self.raw["shift_sunday_default"]),
        )


def _deep_merge(base: dict, override: dict) -> dict:
    """Return base updated with override, recursing into nested dicts.

    Lists and scalars in ``override`` replace the base value wholesale (so a
    port can fully redefine, e.g., ``daily_caps`` or an exclusion list).
    """
    out = copy.deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = copy.deepcopy(val)
    return out


def available_ports() -> list[str]:
    """Return the list of ports that have allocation rules configured."""
    return sorted(PORT_ALLOCATION_RULES.keys())


def has_port_rules(port: str) -> bool:
    """True if ``port`` (case-insensitive) has a configured rule set."""
    return port is not None and str(port).strip().upper() in PORT_ALLOCATION_RULES


def get_port_rules(port: str) -> PortRules:
    """Return the merged :class:`PortRules` for a port code.

    Raises KeyError with a helpful message if the port is not configured, so
    callers can guide the user toward adding it to PORT_ALLOCATION_RULES.
    """
    if port is None:
        raise KeyError("No port specified for allocation rules.")
    key = str(port).strip().upper()
    if key not in PORT_ALLOCATION_RULES:
        raise KeyError(
            f"No allocation rules configured for port '{key}'. "
            f"Configured ports: {available_ports()}. "
            f"Add an entry to PORT_ALLOCATION_RULES in "
            f"config/port_allocation_rules.py to enable it."
        )
    merged = _deep_merge(DEFAULT_RULES, PORT_ALLOCATION_RULES[key])
    return PortRules(port=key, raw=merged)
