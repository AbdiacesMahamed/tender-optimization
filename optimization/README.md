# Optimization Module

Carrier allocation optimization strategies for the Tender Optimization system.

## Structure

```
optimization/
├── __init__.py              # Module exports
├── optimization.py          # Main entry point
├── linear_programming.py    # LP optimization (cost vs performance)
├── cascading_logic.py       # LP + historical growth constraints
├── cheapest_logic.py        # Cheapest carrier allocation
├── performance_logic.py     # Highest performance allocation
└── historic_volume.py       # Historical volume analysis
```

## Quick Usage

```python
from optimization import optimize_allocation

# LP optimization (default: 70% cost, 30% performance)
result = optimize_allocation(data, strategy="linear_programming")

# Cheapest carrier only
result = optimize_allocation(data, strategy="cheapest")

# Highest performance only
result = optimize_allocation(data, strategy="performance")

# Custom weights
result = optimize_allocation(data, cost_weight=0.8, performance_weight=0.2)
```

## Strategies

| Strategy             | Description                                              |
| -------------------- | -------------------------------------------------------- |
| `linear_programming` | Weighted LP optimization balancing cost and performance  |
| `cheapest`           | Allocates all volume to lowest-cost carrier per lane     |
| `performance`        | Allocates all volume to best-performing carrier per lane |

## Cascading Allocation

The `cascading_allocate_with_constraints()` function adds historical constraints:

1. Run LP to rank carriers
2. Calculate historical volume shares (last 5 weeks)
3. Limit growth to historical + max_growth% (default 30%)
4. Cascade remaining volume to next-ranked carriers

## Data Requirements

Required columns:

- `Dray SCAC(FL)` - Carrier SCAC
- `Container Count` - Number of containers
- `Base Rate` - Cost per container
- `Performance_Score` - Performance metric (0-1)
- Grouping: `Lane`, `Week Number`, `Category`, `Facility`, `Discharged Port`

## See Also

Full documentation: [docs/OPTIMIZATION.md](../docs/OPTIMIZATION.md)
