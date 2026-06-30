# Constraints System Documentation

The Tender Optimization system supports operational constraints that control how containers are allocated to carriers.

> For the **behavioral rules** behind this system (precedence, scope-filter
> matching, ceiling semantics, cross-priority crediting, pipeline order), see
> [Constraint Rules & Mechanics](CONSTRAINTS_RULES.md).

## Constraint File Format

Upload an Excel file with the following columns:

| Column                    | Required    | Description                                                          |
| ------------------------- | ----------- | ------------------------------------------------------------------- |
| `Priority Score`          | ✅ Yes      | Higher scores are processed first                                   |
| `Carrier`                 | Conditional | Target carrier for allocation (the assignment TARGET, not a filter) |
| `Category`                | No          | Filter by category (FBA FCL, Retail CD, etc.)                       |
| `Lane`                    | No          | Filter by lane (4-char facility code matches the lane suffix)       |
| `Port`                    | No          | Filter by Discharged Port (`NYC`/`LAX` shorthand expands to aliases)|
| `Week Number`             | No          | Filter by week                                                      |
| `Day of Week`             | No          | Filter by Ocean ETA weekday — Excel WEEKDAY (Sun=1 … Sat=7) or a name (`monday`) |
| `Terminal`                | No          | Filter by terminal                                                  |
| `SSL`                     | No          | Filter by steamship line code                                       |
| `Vessel`                  | No          | Filter by vessel name                                               |
| `Maximum Container Count` | No          | Hard cap on containers for carrier (`0` = lockout)                  |
| `Minimum Container Count` | No          | Minimum containers for carrier                                      |
| `Percent Allocation`      | No          | Target percentage allocation (`0` = lockout)                        |
| `Excluded FC`             | No          | Facility where carrier cannot receive volume                        |

**Scope filters stack with AND.** All filter columns (`Category`, `Lane`, `Port`,
`Week Number`, `Day of Week`, `Terminal`, `SSL`, `Vessel`) combine — a row applies
only where *every* populated filter matches; a blank filter means "all". `Carrier`
is **not** a filter: it names the carrier the matched containers are assigned *to*.

## Constraint Types

### 1. Maximum Container Constraint

Limits the number of containers a carrier can receive.

**How it works:**

1. Allocate up to the maximum number of containers to the carrier
2. These containers go to the **Constrained Table** (locked, won't change)
3. The carrier is excluded from receiving additional volume in optimization
4. Remaining volume is available for other carriers

**Example:**

```
Carrier: ATMI
Category: FBA FCL
Maximum Container Count: 100
Priority Score: 10
```

Result: ATMI gets exactly 100 containers for FBA FCL, locked in constrained table.

### 2. Excluded FC (Facility) Constraint

Prevents a carrier from receiving containers at a specific facility.

**Requirements:**

- Must specify a Carrier (required when using Excluded FC)
- Specify the facility code to exclude

**How it works:**

1. Carrier cannot receive containers at the excluded facility
2. If carrier already has containers there, they are reallocated to other carriers
3. System checks rate data for capable alternative carriers
4. Alternative carriers must not have their own FC exclusion for that facility

**Example:**

```
Carrier: XPDR
Excluded FC: HGR6
Priority Score: 15
```

Result: XPDR cannot service any containers at HGR6 facility.

### 3. Percent Allocation Constraint

Allocates a percentage of volume to a carrier.

**Example:**

```
Carrier: HDDR
Lane: USBALHGR6
Percent Allocation: 30%
Priority Score: 8
```

Result: HDDR receives 30% of containers on the USBAL-HGR6 lane.

The percent **denominator is the original scope pool** (a snapshot taken before
any constraint ran), so "30%" always means 30% of the original eligible volume —
not 30% of whatever a higher-priority rule left behind. If the original-pool target
no longer fits in what's still available, the engine degrades gracefully to "30% of
the remainder" and flags the shortfall in the summary.

### Combining amounts, lockouts, and cap enforcement

A single row can combine `Minimum`, `Maximum`, and `Percent` (e.g. `Minimum 20` +
`Maximum 40` is a 20–40 band; `Percent 30` + `Maximum 40` is 30% of the pool, never
above 40). A `Maximum` or `Percent` of **`0` is a lockout** — the carrier gets
nothing in that scope *and* the optimizer is barred from sending it any. A scoped
cap binds the carrier's **total** volume across **both** tables and **exactly per
scope dimension**, so disjoint caps (e.g. a per-vessel cap and a per-terminal cap)
don't cannibalize each other. Allocated volume is also **spread round-robin across
the week** by Ocean ETA weekday (Fri/Sat/Sun = one bucket).

> These behaviors — combination order, lockouts, both-table/per-dimension cap
> enforcement, cross-priority crediting, and the even-weekly spread — are documented
> in full in [Constraint Rules & Mechanics](CONSTRAINTS_RULES.md).

## Data Flow

```
┌─────────────────────┐
│   Original Data     │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Apply Constraints   │
│ (by Priority Score) │
└─────────┬───────────┘
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
┌───────┐   ┌───────────┐
│Const- │   │Unconst-   │
│rained │   │rained     │
│Table  │   │Table      │
└───────┘   └─────┬─────┘
                  │
                  ▼
         ┌────────────────┐
         │ Optimization   │
         │ Scenarios      │
         └────────────────┘
```

## Constrained vs Unconstrained Tables

| Constrained Table                       | Unconstrained Table                |
| --------------------------------------- | ---------------------------------- |
| Locked allocations                      | Available for optimization         |
| Won't change with scenarios             | Changes based on selected scenario |
| Shows original + constraint assignments | Shows remaining volume             |
| Priority-based allocation               | Algorithm-based allocation         |

## Carrier Reallocation Logic

When containers cannot be allocated to their original carrier (due to FC exclusions):

1. **First**: Check current data for other carriers serving that lane
2. **Second**: If none found, check rate data for capable carriers
3. **Validation**: Ensure alternative carrier:
   - Has rates for that lane
   - Is not excluded from that facility
   - Has not exceeded maximum allocation

## Priority Processing

Constraints are processed in order of Priority Score (highest first):

1. Higher priority constraints are applied first
2. Lower priority constraints work with remaining volume
3. Conflicts are resolved by priority order

## Example Constraints File

| Priority Score | Carrier | Category  | Lane      | SSL  | Maximum Container Count | Excluded FC |
| -------------- | ------- | --------- | --------- | ---- | ----------------------- | ----------- |
| 20             | ATMI    | FBA FCL   |           |      | 150                     |             |
| 15             | XPDR    |           |           | MAEU |                         | HGR6        |
| 10             | HDDR    | Retail CD | USBALHGR6 |      | 75                      |             |
| 5              | FRQT    |           |           |      | 50                      | BWI4        |

This example:

1. First gives ATMI up to 150 FBA FCL containers
2. Then excludes XPDR from HGR6 facility (for MAEU steamship line only)
3. Then gives HDDR up to 75 Retail CD containers on USBAL-HGR6 lane
4. Finally gives FRQT up to 50 containers (not at BWI4 facility)
