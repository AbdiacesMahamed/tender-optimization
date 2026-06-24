"""
Read-only flip / cost simulation for the Tender Optimization assistant.

This module is the analytical core behind questions like
*"flip these containers to ATMI — what's the cost?"*. It is deliberately
**pure**: no Streamlit, no network, no Bedrock — so it can be unit-tested and
adversarially probed in isolation, exactly like ``tools.py``. Every public
method copies its inputs before touching them, so a simulation can never mutate
the dashboard's working data. That property is what makes the assistant
"answer + simulate only" — it can price a flip but never perform one.

The Bedrock Converse tool layer (``tool_specs.py`` / ``tools.py`` / ``chat_ui.py``)
wraps these methods so the model can request a simulation but cannot fabricate a
cost figure.

Cost model (mirrors ``components/data_processor.merge_all_data``):

    Total Rate = Base Rate x Container Count
    Total CPC  = CPC       x Container Count

A "flip" of a group of containers to a target carrier is priced by the same
join the dashboard uses: the rate lookup key is ``SCAC + Lane`` (because
``Lane = Port + Facility`` and ``Lookup = SCAC + Port + Facility``). So to
re-price a lane under a new carrier we rebuild ``target_scac + Lane`` and look
the rate up in the rate sheet — exactly how ``merge_all_data`` joins on
``Lookup``. Lanes where the target carrier has no published rate are reported
as *unrated* rather than silently priced at $0 (a bug the dashboard itself was
burned by — see docs/ARCHITECTURE.md "Common Pitfalls").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

# These imports are intentionally Streamlit-free.
from config.carrier_mapping import CARRIER_NAMES, get_carrier_name, resolve_scac
from config.category_mapping import canonical_category
from components.reporting.container_tracer import (
    get_container_movement_summary,
    parse_container_ids,
)

CARRIER_COL = "Dray SCAC(FL)"
COUNT_COL = "Container Count"
CONTAINER_COL = "Container Numbers"
LANE_COL = "Lane"


def _normalize_facility(value: Any) -> str:
    """Match components.utils.normalize_facility_code without importing Streamlit transitively."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    fc = str(value).strip()
    if not fc:
        return ""
    if fc.upper().startswith("AMAZON"):
        return fc[-4:].upper()
    return fc[:4].upper() if len(fc) >= 4 else fc.upper()


@dataclass
class CarrierResolution:
    """Result of turning a free-text carrier reference into a canonical SCAC."""

    query: str
    scac: str
    name: str
    known: bool  # True if the SCAC is in the carrier master or appears in the data/rates

    def as_dict(self) -> Dict[str, Any]:
        return {"query": self.query, "scac": self.scac, "name": self.name, "known": self.known}


@dataclass
class Scope:
    """A selection of rows to act on.

    Every field is optional; an all-``None`` scope means "everything in the
    working data". Fields combine with AND. ``container_ids`` matches a row if
    *any* of the row's containers is in the requested set.
    """

    carriers: Optional[List[str]] = None      # current SCAC(s) to match
    ports: Optional[List[str]] = None         # Discharged Port value(s)
    facilities: Optional[List[str]] = None    # facility code(s), normalized
    weeks: Optional[List[int]] = None         # Week Number(s)
    categories: Optional[List[str]] = None    # Category value(s)
    container_ids: Optional[List[str]] = None # specific container IDs
    raw: Dict[str, Any] = field(default_factory=dict)  # echo of what the agent asked for

    @classmethod
    def from_dict(cls, raw: Any) -> "Scope":
        """Build a Scope from arbitrary tool input, tolerating missing/garbage fields.

        A scalar is accepted where a list is expected ("ATMI" -> ["ATMI"]);
        blanks and Nones are dropped; unknown keys are ignored. Never raises.
        """
        if not isinstance(raw, dict):
            return cls(raw={"_invalid": raw})

        def _list(key: str) -> Optional[List[Any]]:
            v = raw.get(key)
            if v is None:
                return None
            if isinstance(v, (str, int, float)):
                v = [v]
            if not isinstance(v, list):
                return None
            cleaned = [x for x in v if x is not None and str(x).strip() != ""]
            return cleaned or None

        return cls(
            carriers=_list("carriers"),
            ports=_list("ports"),
            facilities=_list("facilities"),
            weeks=_list("weeks"),
            categories=_list("categories"),
            container_ids=_list("container_ids"),
            raw=raw,
        )

    def is_empty_spec(self) -> bool:
        return not any(
            [self.carriers, self.ports, self.facilities, self.weeks,
             self.categories, self.container_ids]
        )

    def mask(self, df: pd.DataFrame) -> pd.Series:
        """Boolean mask selecting the rows this scope refers to."""
        m = pd.Series(True, index=df.index)

        if self.carriers and CARRIER_COL in df.columns:
            wanted = {resolve_scac(c) for c in self.carriers}
            m &= df[CARRIER_COL].astype(str).str.strip().isin(wanted)

        if self.ports and "Discharged Port" in df.columns:
            wanted = {str(p).strip().upper() for p in self.ports}
            m &= df["Discharged Port"].astype(str).str.strip().str.upper().isin(wanted)

        if self.facilities and "Facility" in df.columns:
            wanted = {_normalize_facility(f) for f in self.facilities}
            norm = df["Facility"].map(_normalize_facility)
            m &= norm.isin(wanted)

        if self.weeks and "Week Number" in df.columns:
            wk = pd.to_numeric(df["Week Number"], errors="coerce")
            wanted = set()
            for w in self.weeks:
                try:
                    wanted.add(int(w))
                except (TypeError, ValueError):
                    continue
            m &= wk.isin(wanted)

        if self.categories and "Category" in df.columns:
            # Canonicalize both sides so 'CD' / 'Retail CD' / 'FBA FCL' all match
            # the normalized data bucket, in both directions (config.category_mapping).
            wanted = {canonical_category(c) for c in self.categories}
            m &= df["Category"].map(canonical_category).isin(wanted)

        if self.container_ids and CONTAINER_COL in df.columns:
            wanted = {str(c).strip().upper() for c in self.container_ids if str(c).strip()}
            if wanted:
                def _row_has(cn: Any) -> bool:
                    return any(cid.upper() in wanted for cid in parse_container_ids(cn))
                m &= df[CONTAINER_COL].map(_row_has)
            else:
                m &= False

        return m


class FlipSimulator:
    """Holds a snapshot of the working data + rate sheet and answers cost questions.

    Parameters
    ----------
    working_data : pd.DataFrame
        The current allocation the user is looking at (already filtered/deduped).
        Copied on construction — the simulator never holds a live reference.
    rate_data : pd.DataFrame, optional
        The rate sheet (carries ``Lookup``, ``Base Rate``, optionally ``CPC``).
        Used to re-price flips to carriers not currently on a lane.
    rate_type : str
        ``"Base Rate"`` (default) or ``"CPC"`` — which cost column to report.
    """

    def __init__(
        self,
        working_data: pd.DataFrame,
        rate_data: Optional[pd.DataFrame] = None,
        rate_type: str = "Base Rate",
    ) -> None:
        if working_data is None:
            working_data = pd.DataFrame()
        self.data = working_data.copy()
        self.rate_type = "CPC" if str(rate_type).upper() == "CPC" else "Base Rate"
        self._rate_col = self.rate_type
        self._total_col = "Total CPC" if self.rate_type == "CPC" else "Total Rate"
        self._rate_index = self._build_rate_index(rate_data)
        # Carriers that exist anywhere we can see — used to judge "known" carriers.
        self._known_scacs = set(CARRIER_NAMES)
        if CARRIER_COL in self.data.columns:
            self._known_scacs |= set(self.data[CARRIER_COL].dropna().astype(str).str.strip())
        self._known_scacs |= {scac for (scac, _lane) in self._rate_index_keys()}

    # ---- rate index -------------------------------------------------------

    def _build_rate_index(self, rate_data: Optional[pd.DataFrame]) -> Dict[str, float]:
        """Map rate-sheet ``Lookup`` -> rate (for the active rate_type)."""
        index: Dict[str, float] = {}
        if rate_data is None or rate_data.empty or "Lookup" not in rate_data.columns:
            return index
        col = self._rate_col if self._rate_col in rate_data.columns else None
        if col is None:
            # Fall back to Base Rate if CPC was requested but unavailable.
            col = "Base Rate" if "Base Rate" in rate_data.columns else None
        if col is None:
            return index
        sub = rate_data[["Lookup", col]].copy()
        sub["Lookup"] = sub["Lookup"].astype(str).str.strip()
        sub[col] = pd.to_numeric(sub[col], errors="coerce")
        sub = sub.dropna(subset=[col])
        # Keep the cheapest published rate if a lookup appears more than once.
        for lk, rate in sub.sort_values(col).groupby("Lookup")[col].first().items():
            index[lk] = float(rate)
        return index

    def _rate_index_keys(self):
        for lk in self._rate_index:
            scac = lk[:4]
            yield scac, lk[4:]

    def _rate_for(self, scac: str, lane: Any) -> Optional[float]:
        """Published rate for a carrier on a lane, or None if unrated."""
        if lane is None or (isinstance(lane, float) and pd.isna(lane)):
            return None
        return self._rate_index.get(f"{scac}{str(lane).strip()}")

    # ---- carrier resolution ----------------------------------------------

    def resolve_carrier(self, query: str) -> CarrierResolution:
        """Turn 'ATMI' / 'Cargomatic' / 'atlas' into a canonical SCAC + known flag."""
        scac = resolve_scac(query) if query else ""
        known = bool(scac) and scac in self._known_scacs
        return CarrierResolution(query=query or "", scac=scac, name=get_carrier_name(scac), known=known)

    # ---- inspection -------------------------------------------------------

    def describe_scope(self, scope: Scope) -> Dict[str, Any]:
        """Summarize what a scope currently selects: carriers, volume, lanes."""
        if self.data.empty:
            return {"matched_rows": 0, "containers": 0, "current_cost": 0.0,
                    "lanes": 0, "carriers": {}, "note": "No working data loaded."}
        sub = self.data[scope.mask(self.data)]
        if sub.empty:
            return {"matched_rows": 0, "containers": 0, "current_cost": 0.0,
                    "lanes": 0, "carriers": {},
                    "note": "No containers match that selection."}
        carriers: Dict[str, int] = {}
        if CARRIER_COL in sub.columns:
            grp = sub.groupby(sub[CARRIER_COL].astype(str))[COUNT_COL].sum()
            carriers = {k: int(v) for k, v in grp.items()}
        return {
            "matched_rows": int(len(sub)),
            "containers": int(self._containers(sub)),
            "current_cost": round(self._cost(sub), 2),
            "lanes": int(sub[LANE_COL].nunique()) if LANE_COL in sub.columns else 0,
            "carriers": carriers,
        }

    # ---- the core question: what does a flip cost? -----------------------

    def simulate_flip(self, scope: Scope, target_carrier: str) -> Dict[str, Any]:
        """Re-price the scoped containers as if moved to ``target_carrier``.

        Returns a structured, agent-friendly dict: resolved target, current vs
        new cost, delta, rated/unrated split, per-lane breakdown, and a
        container-movement narrative. Read-only — ``self.data`` is untouched.
        """
        resolution = self.resolve_carrier(target_carrier)
        target = resolution.scac

        if self.data.empty:
            return {"error": "No working data loaded.", "target": resolution.as_dict()}

        sel = scope.mask(self.data)
        sub = self.data[sel]
        if sub.empty:
            return {
                "target": resolution.as_dict(),
                "matched_rows": 0,
                "containers": 0,
                "note": "No containers match that selection — nothing to flip.",
                "scope": scope.raw,
            }

        if not resolution.known:
            # Don't refuse — price what we can, but flag the unknown carrier loudly.
            note_unknown = (
                f"'{target_carrier}' did not resolve to a known carrier (best guess "
                f"SCAC '{target}'). Costs below assume that SCAC; verify it is correct."
            )
        else:
            note_unknown = None

        current_cost = self._cost(sub)

        # Build the flipped copy.
        flipped = sub.copy()
        flipped[CARRIER_COL] = target

        per_lane: List[Dict[str, Any]] = []
        new_total = 0.0
        rated_containers = 0
        unrated_containers = 0
        unrated_lanes: List[str] = []

        # Group by lane so each lane is priced once under the target carrier.
        lane_series = sub[LANE_COL] if LANE_COL in sub.columns else pd.Series([""] * len(sub), index=sub.index)
        for lane, lane_rows in sub.groupby(lane_series):
            containers = int(lane_rows[COUNT_COL].sum())
            cur_lane_cost = self._cost(lane_rows)
            rate = self._rate_for(target, lane)
            if rate is None:
                unrated_containers += containers
                unrated_lanes.append(str(lane))
                per_lane.append({
                    "lane": str(lane),
                    "containers": containers,
                    "current_cost": round(cur_lane_cost, 2),
                    "new_rate": None,
                    "new_cost": None,
                    "rated": False,
                })
            else:
                lane_new = rate * containers
                new_total += lane_new
                rated_containers += containers
                per_lane.append({
                    "lane": str(lane),
                    "containers": containers,
                    "current_cost": round(cur_lane_cost, 2),
                    "new_rate": round(rate, 2),
                    "new_cost": round(lane_new, 2),
                    "rated": True,
                })

        # Cost delta is only meaningful over the rated lanes (we can't price the rest).
        rated_mask = pd.Series(
            [self._rate_for(target, lane_series.loc[i]) is not None for i in sub.index],
            index=sub.index,
        )
        current_cost_rated = self._cost(sub[rated_mask]) if rated_mask.any() else 0.0
        delta = new_total - current_cost_rated
        pct = (delta / current_cost_rated * 100.0) if current_cost_rated > 0 else None

        # Movement narrative (who currently holds these containers).
        movement = get_container_movement_summary(flipped, sub, carrier_col=CARRIER_COL)

        result: Dict[str, Any] = {
            "target": resolution.as_dict(),
            "rate_type": self.rate_type,
            "matched_rows": int(len(sub)),
            "containers": int(self._containers(sub)),
            "current_cost_all": round(current_cost, 2),
            "current_cost_rated": round(current_cost_rated, 2),
            "new_cost_rated": round(new_total, 2),
            "cost_delta": round(delta, 2),
            "cost_delta_pct": round(pct, 2) if pct is not None else None,
            "cheaper": delta < 0,
            "rated_containers": rated_containers,
            "unrated_containers": unrated_containers,
            "unrated_lanes": sorted(set(unrated_lanes)),
            "per_lane": sorted(per_lane, key=lambda d: d["containers"], reverse=True),
            "scope": scope.raw,
        }
        if movement and "total_flipped" in movement:
            result["containers_changing_carrier"] = int(movement["total_flipped"])
            result["containers_already_on_target"] = int(movement.get("total_kept", 0))
        notes = [n for n in [note_unknown,
                             (f"{unrated_containers} container(s) on {len(set(unrated_lanes))} lane(s) "
                              f"have no published {self.rate_type} for {target} and were left unpriced."
                              if unrated_containers else None)] if n]
        if notes:
            result["notes"] = notes
        return result

    def compare_carriers(self, scope: Scope, candidates: List[str]) -> Dict[str, Any]:
        """Price the same scoped containers under several candidate carriers."""
        options = []
        for cand in candidates:
            sim = self.simulate_flip(scope, cand)
            if "error" in sim or sim.get("matched_rows", 0) == 0:
                continue
            options.append({
                "carrier": sim["target"]["scac"],
                "name": sim["target"]["name"],
                "known": sim["target"]["known"],
                "new_cost_rated": sim["new_cost_rated"],
                "cost_delta": sim["cost_delta"],
                "cost_delta_pct": sim["cost_delta_pct"],
                "unrated_containers": sim["unrated_containers"],
            })
        options.sort(key=lambda o: o["new_cost_rated"])
        base = self.describe_scope(scope)
        return {
            "current_cost": base.get("current_cost", 0.0),
            "containers": base.get("containers", 0),
            "options": options,
            "cheapest": options[0] if options else None,
            "scope": scope.raw,
        }

    def flip_report(self, scope: Scope, target_carrier: str,
                    max_rows: int = 200) -> Dict[str, Any]:
        """Per-container carrier-flip report: old vs new carrier rate and savings.

        This is the auditable, container-level companion to ``simulate_flip``
        (which reports lane-level aggregates). For every container in scope it
        records the current ("old") carrier and its rate, the target ("new")
        carrier and its rate, and the per-container savings — the same shape as
        the standalone Carrier Flip report's "GVT with New SCAC" sheet:

            Old Rate = rate for the ORIGINAL carrier on this lane
            New Rate = rate for the TARGET carrier on this lane
            Savings  = Old Rate - New Rate  (positive = cost reduction)

        Read-only: ``self.data`` is never mutated. ``max_rows`` caps the
        per-container ``rows`` list; ``rows_omitted`` reports how many were
        dropped so the cap is never silent.
        """
        resolution = self.resolve_carrier(target_carrier)
        target = resolution.scac

        if self.data.empty:
            return {"error": "No working data loaded.", "target": resolution.as_dict()}

        sub = self.data[scope.mask(self.data)]
        if sub.empty:
            return {
                "target": resolution.as_dict(),
                "matched_rows": 0,
                "containers": 0,
                "note": "No containers match that selection — nothing to report.",
                "scope": scope.raw,
            }

        has_ids = CONTAINER_COL in sub.columns
        rows: List[Dict[str, Any]] = []
        lane_acc: Dict[str, Dict[str, Any]] = {}

        total_containers = 0
        priced_both = 0          # containers with BOTH an old and a new rate
        total_old_cost = 0.0     # over priced_both only
        total_new_cost = 0.0     # over priced_both only
        unpriced_old = 0
        unpriced_new = 0
        changing = 0
        already_on_target = 0

        for _, r in sub.iterrows():
            old_scac = str(r.get(CARRIER_COL, "")).strip() if CARRIER_COL in sub.columns else ""
            lane = r.get(LANE_COL) if LANE_COL in sub.columns else None
            lane_key = (str(lane).strip()
                        if lane is not None and not (isinstance(lane, float) and pd.isna(lane))
                        else "")

            if has_ids:
                container_ids = parse_container_ids(r.get(CONTAINER_COL))
            else:
                container_ids = []
            if not container_ids:
                # No parseable IDs — fall back to the row's count as anonymous units.
                n = int(pd.to_numeric(pd.Series([r.get(COUNT_COL, 0)]), errors="coerce").fillna(0).iloc[0])
                container_ids = [None] * n

            old_rate = self._rate_for(old_scac, lane) if old_scac else None
            new_rate = self._rate_for(target, lane)
            savings = (old_rate - new_rate) if (old_rate is not None and new_rate is not None) else None
            flips = old_scac != target

            la = lane_acc.setdefault(lane_key, {
                "lane": lane_key, "containers": 0, "old_carriers": set(),
                "old_rate": old_rate, "new_rate": new_rate, "savings": 0.0,
                "rated": old_rate is not None and new_rate is not None,
                "_old_rate_ambiguous": False,
            })
            # A lane can carry more than one old carrier; if their rates differ,
            # there is no single representative old rate for the lane.
            if la["old_rate"] != old_rate:
                la["_old_rate_ambiguous"] = True

            for cid in container_ids:
                total_containers += 1
                if old_rate is None:
                    unpriced_old += 1
                if new_rate is None:
                    unpriced_new += 1
                if old_rate is not None and new_rate is not None:
                    priced_both += 1
                    total_old_cost += old_rate
                    total_new_cost += new_rate
                    la["savings"] += savings
                changing += 1 if flips else 0
                already_on_target += 0 if flips else 1

                la["containers"] += 1
                if old_scac:
                    la["old_carriers"].add(old_scac)

                if len(rows) < max_rows:
                    rows.append({
                        "container": cid,
                        "lane": lane_key,
                        "old_carrier": old_scac or None,
                        "old_rate": round(old_rate, 2) if old_rate is not None else None,
                        "new_carrier": target,
                        "new_rate": round(new_rate, 2) if new_rate is not None else None,
                        "savings": round(savings, 2) if savings is not None else None,
                        "flips": flips,
                    })

        total_savings = total_old_cost - total_new_cost
        savings_pct = (total_savings / total_old_cost * 100.0) if total_old_cost > 0 else None

        per_lane = []
        for la in lane_acc.values():
            # Don't report a single old_rate for a lane whose old carriers differ.
            lane_old_rate = (None if la["_old_rate_ambiguous"]
                             else (round(la["old_rate"], 2) if la["old_rate"] is not None else None))
            per_lane.append({
                "lane": la["lane"],
                "containers": la["containers"],
                "old_carriers": sorted(la["old_carriers"]),
                "old_rate": lane_old_rate,
                "new_rate": round(la["new_rate"], 2) if la["new_rate"] is not None else None,
                "savings": round(la["savings"], 2) if la["rated"] else None,
                "rated": la["rated"],
            })
        per_lane.sort(key=lambda d: d["containers"], reverse=True)

        result: Dict[str, Any] = {
            "target": resolution.as_dict(),
            "rate_type": self.rate_type,
            "matched_rows": int(len(sub)),
            "containers": total_containers,
            "containers_priced": priced_both,
            "containers_changing_carrier": changing,
            "containers_already_on_target": already_on_target,
            "total_old_cost": round(total_old_cost, 2),
            "total_new_cost": round(total_new_cost, 2),
            "total_savings": round(total_savings, 2),
            "savings_pct": round(savings_pct, 2) if savings_pct is not None else None,
            "cheaper": total_savings > 0,
            "unpriced_old_containers": unpriced_old,
            "unpriced_new_containers": unpriced_new,
            "per_lane": per_lane,
            "rows": rows,
            "rows_omitted": max(0, total_containers - len(rows)),
            "scope": scope.raw,
        }

        notes = []
        if not resolution.known:
            notes.append(
                f"'{target_carrier}' did not resolve to a known carrier (best guess "
                f"SCAC '{target}'). Rates below assume that SCAC; verify it is correct."
            )
        if unpriced_new:
            notes.append(
                f"{unpriced_new} container(s) have no published {self.rate_type} for "
                f"{target} and could not be priced under the new carrier."
            )
        if unpriced_old:
            notes.append(
                f"{unpriced_old} container(s) have no published {self.rate_type} for "
                f"their current carrier, so their savings could not be computed."
            )
        if notes:
            result["notes"] = notes
        return result

    def lane_rate_options(self, scope: Scope, top_n: int = 8) -> Dict[str, Any]:
        """For the lanes in scope, list carriers that have a published rate."""
        if self.data.empty or LANE_COL not in self.data.columns:
            return {"lanes": [], "note": "No lane data available."}
        sub = self.data[scope.mask(self.data)]
        lanes = sorted(sub[LANE_COL].dropna().astype(str).unique())
        out = []
        for lane in lanes:
            carriers = []
            for scac, l in self._rate_index_keys():
                if l == lane:
                    rate = self._rate_index[f"{scac}{lane}"]
                    carriers.append({"carrier": scac, "name": get_carrier_name(scac),
                                     "rate": round(rate, 2)})
            carriers.sort(key=lambda c: c["rate"])
            out.append({"lane": lane, "carriers": carriers[:top_n]})
        return {"rate_type": self.rate_type, "lanes": out, "scope": scope.raw}

    # ---- cost helpers -----------------------------------------------------

    def _cost(self, df: pd.DataFrame) -> float:
        """Total cost of a slice using the active rate type, robust to missing columns."""
        if df.empty:
            return 0.0
        if self._total_col in df.columns:
            return float(pd.to_numeric(df[self._total_col], errors="coerce").fillna(0).sum())
        # Reconstruct from rate x count if the total column is absent.
        if self._rate_col in df.columns and COUNT_COL in df.columns:
            rate = pd.to_numeric(df[self._rate_col], errors="coerce").fillna(0)
            cnt = pd.to_numeric(df[COUNT_COL], errors="coerce").fillna(0)
            return float((rate * cnt).sum())
        return 0.0

    @staticmethod
    def _containers(df: pd.DataFrame) -> int:
        if COUNT_COL in df.columns:
            return int(pd.to_numeric(df[COUNT_COL], errors="coerce").fillna(0).sum())
        return 0
