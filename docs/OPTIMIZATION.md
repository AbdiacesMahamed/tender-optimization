# Optimization Strategies Documentation

The Tender Optimization system provides multiple strategies for allocating containers to carriers.

## Standard Output Columns

All optimization scenarios (Current Selection, Performance, Cheapest Cost, Optimized) export data with these standardized columns for downstream analysis:

| Column                | Description                                                                             |
| --------------------- | --------------------------------------------------------------------------------------- |
| **Carrier Flips**     | Shows container movement: `Had X → From CARRIER (+N), Lost N → To CARRIER (-N) → Now Y` |
| **Container Numbers** | Comma-separated list of container IDs assigned to the carrier                           |
| **NEW SCAC**          | The carrier assigned in this scenario (renamed from `Dray SCAC(FL)`)                    |
| **Discharged Port**   | Port code (e.g., OAK, LAX, BAL)                                                         |
| **Category**          | Container category type                                                                 |
| **Week Number**       | Week number for the allocation                                                          |

> **Note:** The `NEW SCAC` column is intentionally named to distinguish the optimized carrier assignment from the original `Dray SCAC(FL)` in the source data, enabling easy comparison in downstream tools like the Carrier Flip Analysis script.

## Available Scenarios

### 1. Current Selection

Shows the data exactly as it appears in the GVT file without any optimization.

**Use case:** Baseline comparison, understanding current state.

### 2. Performance Scenario

Allocates ALL containers for each lane to the highest-performing carrier.

**Algorithm:**

1. Group containers by Lane + Week + Category
2. Find the carrier with the highest Performance Score in each group
3. Reassign all containers in that group to the best-performing carrier

**Use case:** Maximize service quality, prioritize reliable carriers.

### 3. Cheapest Cost Scenario

Allocates ALL containers for each lane to the carrier with the lowest rate.

**Algorithm:**

1. Group containers by Lane + Week + Category
2. Find the carrier with the lowest Base Rate in each group
3. Reassign all containers in that group to the cheapest carrier

**Use case:** Minimize transportation costs, budget optimization.

### 4. LP + Historical Constraints (Optimized)

Uses Linear Programming to balance cost and performance, with growth constraints based on historical volume.

**Algorithm:**

1. **LP Ranking**: Score carriers using weighted combination:

   ```
   Score = (Cost Weight × Normalized Cost) + (Performance Weight × Performance Score)
   ```

   Default weights: 70% cost, 30% performance

2. **Historical Analysis**: Calculate each carrier's market share from last 5 weeks

3. **Growth Limits**: Cap allocation at historical share + max growth %
   - Default max growth: 30%
   - Example: Carrier with 20% historical share can grow to max 26% (20% × 1.3)

4. **Cascading Allocation**:
   - Allocate to Rank 1 carrier up to their growth limit
   - Cascade remaining volume to Rank 2, then Rank 3, etc.
   - If volume remains after all carriers hit limits, assign to Rank 1

**Use case:** Balanced optimization respecting operational constraints.

## LP Optimization Details

### Weight Configuration

The LP optimization uses configurable weights:

| Weight             | Default | Effect                                 |
| ------------------ | ------- | -------------------------------------- |
| Cost Weight        | 70%     | Higher = prioritize lower costs        |
| Performance Weight | 30%     | Higher = prioritize better performance |

Weights must sum to 100%.

### Carrier Ranking

Carriers are ranked per group (Lane/Week/Category) based on optimization score:

```python
optimization_score = (cost_weight × normalized_cost) + (performance_weight × performance_score)
```

- Lower scores = better (since lower cost is good)
- Rank 1 = best carrier for that group

### Growth Constraints

Historical volume analysis prevents dramatic shifts:

1. Calculate carrier's average volume share over last 5 weeks
2. Apply maximum growth limit (default 30%)
3. New allocation cannot exceed: `historical_share × (1 + max_growth)`

**Example:**

- ATMI had 25% of volume historically
- Max growth = 30%
- Maximum new allocation = 25% × 1.3 = 32.5%

### Excluded Carriers

Carriers with Maximum Container Constraints are excluded from optimization:

- They've already received their allocation in the constrained table
- Their volume in unconstrained table is available for other carriers

## Carrier Flips Tracking

The system tracks how containers move between carriers across scenarios:

### Carrier Flips Column Format

```
Had X → [Changes] → Now Y
```

**Components:**

- `Had X` - Original containers before optimization
- `From CARRIER (+N)` - Gained N containers from CARRIER
- `Lost N → To CARRIER (-N)` - Lost N containers to CARRIER
- `Now Y` - Final container count

**Examples:**

```
Had 4 → From RKNE (+8) + XPDR (+3), Lost 2 → To FROT (-2) → Now 15
Had 10 (kept all) → Now 10
Had 0 → From ATMI (+5) → Now 5
Had 20 → Lost 12 → To ATMI (-8), To XPDR (-4) → Now 8
```

### Container IDs

When container IDs are enabled, the display includes actual container numbers:

```
Had 5 [MRSU3270916, MRSU3826163, MRSU4254334...] → From FRQT (+3) [CAAU8131942, CAAU8310315...] → Now 8
```

## Metrics Displayed

### Per-Scenario Metrics

| Metric            | Description                            |
| ----------------- | -------------------------------------- |
| Total Cost        | Sum of (Base Rate × Container Count)   |
| Total Containers  | Sum of all containers                  |
| Average Rate      | Total Cost / Total Containers          |
| Potential Savings | Current Cost - Optimized Cost          |
| Savings %         | Potential Savings / Current Cost × 100 |

### Carrier Performance Matrix

Shows each carrier's:

- Container allocation
- Average rate
- Performance score
- Volume share percentage

## Integration with Constraints

When constraints are active:

1. **Constrained Table**: Locked allocations from constraint processing
2. **Unconstrained Table**: Remaining volume for optimization
3. **Optimization**: Only runs on unconstrained data
4. **Excluded Carriers**: Carriers with max constraints won't receive more volume

The final result combines:

```
Total = Constrained Containers + Optimized Unconstrained Containers
```

## Best Practices

1. **Start with Current Selection** to understand baseline
2. **Compare Cheapest and Performance** to see trade-offs
3. **Use Optimized** for balanced recommendations
4. **Apply Constraints** for operational requirements
5. **Review Carrier Flips** to understand volume movements
