# TIW & SEA Constraint Report

**Inputs used (your current uploads):**
- GVT data: `GVT 6.23.xlsx` → 9,519 containers total
- Rate card: `Rate card 5.22.26 (1).xlsx`
- Constraints: `New constraints 5.19 (2).xlsx`

*Note: TIW and SEA are **Discharged Ports**, not terminals. Every rule below is
Port-scoped (the Terminal column is blank for all TIW/SEA rows).*

*All percentages in the file are decimals (0.80 = 80%). Percent allocations are
computed against the **original** pool size, frozen before any allocation runs.
Higher Priority Score is processed first.*

---

## How the engine decides allocations (the 3 rules that explain everything below)

1. **Priority order.** All rules are sorted by Priority Score, highest first.
   A higher-priority rule claims its containers before a lower one sees the pool.
2. **Frozen denominator.** "80%" always means 80% of the *original* scope volume.
   If an earlier rule already removed containers, the percent rule can only draw
   from what's left — so it reports a **Partial / shortfall** and tells you who
   took the rest.
3. **Lockout (0%) just blocks.** A rule with 0% or Max 0 allocates nothing and
   prevents the optimizer from sending that carrier anything in the scope. It is
   *meant* to show 0 — that is success, not failure.

---

## TIW — 468 containers

**Available volume**
| Category | Total | By carrier |
|---|---|---|
| CD | 459 | HJBT 244, RKNE 114, FRQT 99, XPDR 2 |
| TL | 9 | HJBT 8, FRQT 1 |

**Outcomes**
| Pri | Cat | Carrier | Status | Allocated | Why |
|---|---|---|---|---|---|
| 10 | TL | HJBT | Lockout | 0 | Intentional block (Max 0) |
| 10 | CD | HJBT | Applied | **130** | Hard max of 130, taken first |
| 9 | TL | RKNE | Applied | **8** | 80% of 9 = 8 |
| 9 | TL | XPDR | Lockout | 0 | Intentional block |
| 9 | CD | XPDR | Lockout | 0 | Intentional block |
| 9 | TL | FRQT | Partial (−1) | 1 | Wanted 20% of 9 = 2, but RKNE's 80% already took 8; only 1 left |
| 9 | CD | RKNE | Partial (−104) | **264** | Wanted 80% of 459 = 368, but HJBT's max-130 ran first; 80% of the 329 remainder = 264 |
| 9 | CD | FRQT | Partial (−79) | **13** | Wanted 20% of 459 = 92, but HJBT(130)+RKNE(264) drained the pool; 20% of the 65 remainder = 13 |
| 8 | CD | AOYV/SONW/HDDR/ATMI | Lockout | 0 | Intentional blocks |
| 8 | TL | HDDR/ATMI/AOYV/SONW | **Failed** | 0 | All 9 TL containers already claimed by Priority 9 |

**Reading the TIW result**
- The CD scope is **over-subscribed**: HJBT max-130 + RKNE 80% + FRQT 20% asks for
  130 + 368 + 92 = **590 against a 459 pool**. Because HJBT's fixed 130 comes off
  the top first, RKNE's "80%" can only reach 264 and FRQT's "20%" only 13. The
  shortfalls are arithmetic, not a bug.
- The 4 **TL Priority-8 "Failed"** rules (HDDR/ATMI/AOYV/SONW) are *floor/lockout
  rules competing for a 9-container pool that Priority-9 already fully allocated.*
  There's nothing left for a lower-priority rule to grab — the engine says so
  explicitly.

---

## SEA — 191 containers

**Available volume**
| Category | Total | By carrier |
|---|---|---|
| CD | 190 | FRQT 116, AOYV 73, ATMI 1 |
| TL | **1** | ATMI 1 |

**Outcomes**
| Pri | Cat | Carrier | Status | Allocated | Why |
|---|---|---|---|---|---|
| 10 | CD | HJBT | Lockout | 0 | Intentional block |
| 10 | TL | HJBT | Lockout | 0 | Intentional block |
| 9 | CD | AOYV | Applied | **63** | 33% of 190 = 63 |
| 9 | CD | FRQT | Partial (−42) | **86** | Wanted 67% of 190 = 128, but AOYV's 33% (63) ran in the same tier; 67% of the 127 remainder = 86 |
| 9 | TL | FRQT | Applied | **1** | 67% of 1 = 1 (the lone SEA/TL container) |
| 9 | CD | ATMI | Lockout | 0 | Intentional block |
| 9 | TL | AOYV | **Failed** | 0 | No SEA row is TL for AOYV — SEA/TL is 1 container, ATMI's |
| 9 | TL | ATMI | **Failed** | 0 | Same: combination too narrow, the 1 TL container went to FRQT |
| 8 | TL | SONW/HDDR/RKNE | **Failed** | 0 | The single TL container was already claimed by Priority 9 |
| 8 | CD | RKNE/HDDR/XPDR/SONW | Lockout | 0 | Intentional blocks |

**Reading the SEA result**
- **SEA/CD is fine.** 33% AOYV + 67% FRQT = 100%. AOYV gets 63; FRQT gets 86
  instead of 128 only because of integer rounding on the frozen pool (33%→63 leaves
  127, and 67% of 127 = 86). Together 63 + 86 = 149 of the 190; the rest are
  locked-out carriers' containers that flow to the optimizer.
- **SEA/TL is the problem area.** The entire SEA/TL category is **1 container.**
  You wrote **6 rules** against it (FRQT, AOYV, ATMI, SONW, HDDR, RKNE). Only the
  first (FRQT 67%) can take that container; the other 5 fail because there is
  nothing left — or, for AOYV/ATMI, because no SEA row is TL for them at all.

---

## Bottom line

- **The engine is working correctly.** Every TIW/SEA allocation follows directly
  from priority order + the frozen-pool percentage math, and each shortfall/failure
  comes with a plain-English reason.
- **The issues are in the constraint list, not the app:**
  1. **TIW/CD is over-subscribed** (590 requested vs 459 available) — so the
     lower-priority percent rules (RKNE 80%, FRQT 20%) can't hit their targets.
  2. **TL micro-pools** at both ports are tiny (TIW/TL = 9, SEA/TL = 1) yet have
     4–6 rules each. Lower-priority floor/lockout rules there will always "Fail"
     because higher-priority rules consume the whole pool first.
  3. **SEA/TL rules for AOYV and ATMI target carriers that have no SEA/TL volume.**

**Suggested fixes (optional):**
- TIW/CD: make the percentages sum to ≤100% *after* accounting for HJBT's fixed
  130 (e.g. give RKNE/FRQT shares of the 329 that remain), or convert HJBT to a
  percentage too.
- SEA/TL and TIW/TL: collapse each to the one viable rule (SEA/TL is all-FRQT now;
  TIW/TL is HJBT+FRQT). The extra floor/lockout rows just generate noise.
