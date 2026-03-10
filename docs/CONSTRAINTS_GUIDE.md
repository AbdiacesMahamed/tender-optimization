# Constraint File Guide

The constraint file is an Excel spreadsheet that controls how containers are allocated to carriers. Constraints lock specific allocations so they are not changed by optimization scenarios.

A template is provided at `docs/constraint_template.xlsx`.

## Columns
![1773075396111](image/CONSTRAINTS_GUIDE/1773075396111.xlsx)
| Column | Required | Type | Description |
|--------|----------|------|-------------|
| Priority Score | Yes | Number | Processing order. Higher = processed first. When two constraints compete for the same containers, the higher priority wins. |
| Carrier | Yes* | Text (SCAC) | The carrier to constrain. Required for Maximum, Minimum, and Excluded FC. |
| Category | No | Text | Filter by business category (e.g., `FBA FCL`, `Retail CD`). Leave blank to match all. |
| Lane | No | Text | Filter by lane code (e.g., `USLAXIUSF`). Leave blank to match all. |
| Port | No | Text | Filter by discharged port (e.g., `LAX`, `BAL`). Leave blank to match all. |
| Week Number | No | Number | Filter by specific week. Leave blank to match all weeks. |
| Terminal | No | Text | Filter by port terminal. Leave blank to match all. |
| SSL | No | Text | Filter by steamship line. Leave blank to match all. |
| Vessel | No | Text | Filter by vessel name. Leave blank to match all. |
| Maximum Container Count | No | Number | Hard cap on containers for this carrier. |
| Minimum Container Count | No | Number | Floor on containers for this carrier. |
| Percent Allocation | No | Number | Percentage of matching containers to assign to this carrier. |
| Excluded FC | No | Text | Facility code where this carrier is banned (e.g., `IUSF`). |

## Constraint Types

### Maximum Container Count
Caps how many containers a carrier can receive. Any excess stays in the unconstrained pool and becomes available to other carriers during optimization.

- The carrier is added to the exclusion list so optimization scenarios won't assign it more volume
- Containers are NOT deleted — they remain available for other carriers
- Works with or without filters

**Example:** XPDR gets at most 200 containers total
```
Priority Score: 100
Carrier: XPDR
Maximum Container Count: 200
```

**Example:** ABCD gets at most 50 containers for FBA FCL on lane USLAXIUSF in week 9
```
Priority Score: 90
Carrier: ABCD
Category: FBA FCL
Lane: USLAXIUSF
Week Number: 9
Maximum Container Count: 50
```

### Minimum Container Count
Guarantees a carrier receives at least this many containers from the matching group.

**Example:** EFGH gets at least 30 containers at port LAX
```
Priority Score: 80
Carrier: EFGH
Port: LAX
Minimum Container Count: 30
```

### Percent Allocation
Assigns a percentage of matching containers to the carrier.

**Example:** IJKL gets 40% of Retail CD containers at BAL in week 10
```
Priority Score: 70
Carrier: IJKL
Category: Retail CD
Port: BAL
Week Number: 10
Percent Allocation: 40
```

### Excluded FC (Facility Exclusion)
Bans a carrier from receiving ANY containers at a specific facility. This applies across all scenarios — the carrier will never be assigned containers at that facility in constrained or unconstrained data.

**Example:** MNOP gets max 100 containers but NOT at facility IUSF
```
Priority Score: 60
Carrier: MNOP
Maximum Container Count: 100
Excluded FC: IUSF
```

**Example:** QRST is banned from facility HGR6 entirely (no volume constraint)
```
Priority Score: 50
Carrier: QRST
Excluded FC: HGR6
```

## How Filters Work

Filters narrow which containers a constraint applies to. They stack — if you specify multiple filters, ALL must match.

| Filters specified | Containers affected |
|---|---|
| None | All containers for that carrier |
| Category only | Only containers in that category |
| Category + Lane | Only containers in that category AND lane |
| Category + Lane + Week | Only containers matching all three |
| Port only | Only containers at that port |

Leave a filter column blank to match all values for that dimension.

## Processing Order

1. Constraints are sorted by Priority Score (highest first)
2. Each constraint is processed in order
3. Matching containers are moved from unconstrained to constrained
4. Once a container is constrained, it cannot be claimed by a lower-priority constraint
5. After all constraints are processed, peel pile allocations are applied (see Peel Pile section below)
6. Remaining unconstrained containers are available for scenario optimization

## How Constraints Affect Scenarios

| Scenario | Constrained containers | Unconstrained containers |
|---|---|---|
| Current Selection | Shown in locked table (not modified) | Shown as-is |
| Performance | Shown in locked table (not modified) | Reallocated to highest performer |
| Cheapest Cost | Shown in locked table (not modified) | Reallocated to cheapest carrier |
| Optimized | Shown in locked table (not modified) | Optimized via LP + historical constraints |

The total cost shown in the cost cards includes both constrained and unconstrained costs.

## Peel Pile

A **peel pile** is a group of containers from the same vessel, week, port, and terminal that meets a minimum volume threshold (30+ containers). These groups are large enough to justify dedicated carrier assignments — either to a single carrier or split across multiple carriers.

### How It Works

1. The dashboard automatically identifies qualifying peel pile groups from the filtered data
2. Groups are defined by **Vessel + Week Number + Discharged Port + Terminal** and must have **30 or more containers**
3. You select a peel pile group and assign one or more carriers
4. Containers are **split equally** across the selected carriers (first carrier(s) get any extra)
5. All assigned containers are locked as constraints (moved from unconstrained to constrained data)

### Splitting Across Carriers

When you assign multiple carriers to a peel pile group, the containers are divided as evenly as possible. If the split is uneven, the first carrier(s) receive one extra container:

| Total Containers | Carriers Selected | Allocation | 
|-----------------|-------------------|------------|
| 47 | 1 (XPDR) | XPDR: 47 |
| 47 | 2 (XPDR, ABCD) | XPDR: 24, ABCD: 23 |
| 30 | 3 (XPDR, ABCD, EFGH) | 10 each |
| 50 | 3 (XPDR, ABCD, EFGH) | XPDR: 17, ABCD: 17, EFGH: 16 |

All containers are always assigned — none are left unconstrained.

### Example: Single Carrier Assignment

Vessel EVER LOTUS in Week 9 at LAX / Terminal A has 45 containers. Assign all to XPDR:
- Select the peel pile group from the dropdown
- Select carrier XPDR
- Click "Add to Queue" → "Apply All"
- All 45 containers are locked to XPDR

### Example: Multi-Carrier Split

Same vessel group (45 containers). Split across XPDR and ABCD:
- Select the peel pile group from the dropdown
- Select both XPDR and ABCD in the carrier multiselect
- Click "Add to Queue" → "Apply All"
- 23 containers assigned to XPDR, 22 to ABCD (first carrier gets the extra)

### Interaction with Constraint File

Peel pile allocations are applied **after** all constraint file rules are processed. This means:

- Containers already claimed by a higher-priority constraint will **not** be available for peel pile assignment
- Peel pile carriers are added to the exclusion set so optimization does not assign them more volume
- Both constraint file allocations and peel pile allocations appear in the constraint summary

### UI Workflow

1. Scroll to the **Peel Pile Analysis** section at the bottom of the analysis table
2. Review the table of qualifying vessel groups (30+ containers)
3. Select a group from the dropdown
4. Use the **multiselect** to pick one or more carriers
5. Click **Add to Queue** — this queues the assignment without recalculating (fast)
6. Repeat for additional groups as needed
7. Click **Apply All** — this locks all queued assignments and triggers a full page recalculation
8. Use **Clear Queue** to discard pending (not yet applied) assignments
9. Use **Clear All** to remove all peel pile assignments entirely

### Download

Click **Download Peel Pile** to export a CSV of all qualifying groups with their assigned carriers and split information.

## Tips

- Use high priority scores (90-100) for hard business rules
- Use lower priority scores (50-70) for soft preferences
- Combine Maximum + Excluded FC to cap a carrier while also banning them from specific facilities
- Use Percent Allocation for proportional splits when you want a carrier to handle a specific share
- The constraint summary in the dashboard shows which constraints were applied and how many containers were affected
- Use peel pile multi-carrier split when a vessel group is too large for a single carrier's capacity
