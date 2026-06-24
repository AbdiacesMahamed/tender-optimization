"""Section 10 trigger-threshold checks for the JBH Allocation Model.

After allocation, these checks scan the result and emit warnings for any
breached threshold. Pure functions over the allocated frame + rules.
"""

from __future__ import annotations

import pandas as pd

from .eligibility import missing_field_rate
from .engine import _is_primary_carrier


def check_triggers(allocated: pd.DataFrame, eligible_in: pd.DataFrame,
                   target: int, rules) -> list[dict]:
    """Return a list of breached-trigger dicts: {trigger, threshold, value, message}.

    Only the triggers computable from a single run's allocation are evaluated
    here (cap, target floor, day concentration, HJBT concentration, missing
    field rate). Accuracy/error/miss-rate triggers require actual outgate data
    and are left to a downstream accuracy module.
    """
    out: list[dict] = []
    t = rules.triggers
    total = len(allocated)

    # Weekly cap exceeded (> 316)
    if total > t["weekly_cap"]:
        out.append({"trigger": "Weekly Cap Exceeded", "threshold": t["weekly_cap"],
                    "value": total, "message": f"Allocation {total} exceeds weekly cap {t['weekly_cap']}"})

    # Hard weekly ceiling (345)
    if total > rules.hard_weekly_ceiling:
        out.append({"trigger": "Hard Ceiling Exceeded", "threshold": rules.hard_weekly_ceiling,
                    "value": total, "message": f"Allocation {total} exceeds hard ceiling {rules.hard_weekly_ceiling}"})

    # Target floor (< 90% of base target)
    floor = int(rules.base_weekly_target * t["target_floor_pct"])
    if total < floor:
        out.append({"trigger": "Target Floor", "threshold": floor, "value": total,
                    "message": f"Allocation {total} below target floor {floor} "
                               f"({t['target_floor_pct']:.0%} of {rules.base_weekly_target})"})

    # Day concentration (> 35% of weekly allocation on any day)
    if total > 0 and "expected_outgate" in allocated.columns:
        by_day = allocated["expected_outgate"].dropna().dt.date.value_counts()
        if not by_day.empty:
            top_day = by_day.idxmax()
            top_share = by_day.max() / total
            if top_share > t["day_concentration_max"]:
                out.append({"trigger": "Day Concentration", "threshold": t["day_concentration_max"],
                            "value": round(top_share, 3),
                            "message": f"{top_day} holds {top_share:.0%} of the week "
                                       f"(> {t['day_concentration_max']:.0%})"})

    # HJBT concentration (> 80%)
    if total > 0:
        hjbt_share = _is_primary_carrier(allocated, rules).mean()
        if hjbt_share > t["hjbt_concentration_max"]:
            out.append({"trigger": "HJBT Concentration", "threshold": t["hjbt_concentration_max"],
                        "value": round(float(hjbt_share), 3),
                        "message": f"HJBT share {hjbt_share:.0%} exceeds {t['hjbt_concentration_max']:.0%}"})

    # Missing field rate (> 5%)
    mfr = missing_field_rate(eligible_in)
    if mfr > t["missing_field_rate_max"]:
        out.append({"trigger": "Missing Field Rate", "threshold": t["missing_field_rate_max"],
                    "value": round(mfr, 3),
                    "message": f"{mfr:.0%} of containers missing a critical field "
                               f"(> {t['missing_field_rate_max']:.0%})"})

    return out
