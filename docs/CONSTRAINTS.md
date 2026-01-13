# Constraints System Documentation

The Tender Optimization system supports operational constraints that control how containers are allocated to carriers.

## Constraint File Format

Upload an Excel file with the following columns:

| Column                    | Required    | Description                                   |
| ------------------------- | ----------- | --------------------------------------------- |
| `Priority Score`          | ✅ Yes      | Higher scores are processed first             |
| `Carrier`                 | Conditional | Target carrier for allocation                 |
| `Category`                | No          | Filter by category (FBA FCL, Retail CD, etc.) |
| `Lane`                    | No          | Filter by lane                                |
| `Port`                    | No          | Filter by port                                |
| `Week Number`             | No          | Filter by week                                |
| `Terminal`                | No          | Filter by terminal                            |
| `SSL`                     | No          | Filter by steamship line code                 |
| `Vessel`                  | No          | Filter by vessel name                         |
| `Maximum Container Count` | No          | Hard cap on containers for carrier            |
| `Minimum Container Count` | No          | Minimum containers for carrier                |
| `Percent Allocation`      | No          | Target percentage allocation                  |
| `Excluded FC`             | No          | Facility where carrier cannot receive volume  |

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
