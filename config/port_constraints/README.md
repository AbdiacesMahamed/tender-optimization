# Prebuilt per-port constraints

One CSV per port (named by its uppercase **Discharged Port** code, e.g. `LAX.csv`).
These are the **always-on** operational constraints that ship with the app and are
enforced on every optimization run, on top of whatever a user uploads or asks the
assistant for.

## Two guarantees

1. **They cannot be overwritten by user constraints.** Prebuilt rows are merged to
   the *front* of the constraint set, so they claim their containers first — even if
   an uploaded or chatbot rule has a higher Priority Score. Priority Score only
   orders rules *within* the prebuilt block.
2. **On/off lives in code only.** Users never see these toggles — only the outcome
   (a confirmation that the standing port constraints were applied). Engineers flip
   them in [`components/constraints/prebuilt.py`](../../components/constraints/prebuilt.py):
   - `PREBUILT_CONSTRAINTS_ENABLED` — master switch for all ports.
   - `ENABLED = {"LAX": True, ...}` — per-port switches.

## Editing the rules

Open the port's CSV and add/edit rows. Columns (only **Priority Score** is required):

| Column | Meaning |
|---|---|
| Priority Score | Required. Higher = processed first within the prebuilt block. |
| Carrier | SCAC the rule assigns volume **to** (the target, not a filter). Required for Max/Min/Percent/Excluded FC. |
| Category, Lane, Port, Week Number, Day of Week, Terminal, SSL, Vessel | Optional scope filters — leave blank for "any". |
| Maximum Container Count | Hard cap (0 = lockout). |
| Minimum Container Count | Floor. |
| Percent Allocation | 0–100 (0 = lockout). |
| Excluded FC | Facility the carrier is banned from. |

A **header-only** CSV (no data rows) is a no-op for that port. Copy `_TEMPLATE.csv`
to start. To add a brand-new port: drop in `<PORT>.csv` and add its code to `ENABLED`.
