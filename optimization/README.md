# Optimization Module

This folder contains all optimization strategies for carrier allocation in the Tender Optimization system.

## Structure

```
optimization/
├── __init__.py                  # Main exports
├── optimization.py              # Main orchestration module (entry point)
├── linear_programming.py        # Linear programming optimization
├── cheapest_logic.py           # Cheapest carrier allocation
└── performance_logic.py        # Highest performance allocation
```

## Usage

### Basic Usage

```python
from optimization import optimize_allocation

# Linear programming with default weights (70% cost, 30% performance)
result = optimize_allocation(data, strategy="linear_programming")

# Custom weights
result = optimize_allocation(
    data,
    strategy="linear_programming",
    cost_weight=0.8,
    performance_weight=0.2
)

# Cheapest carrier only
result = optimize_allocation(data, strategy="cheapest")

# Highest performance only
result = optimize_allocation(data, strategy="performance")
```

### Integration with Streamlit (Slider Example)

```python
import streamlit as st
from optimization import optimize_allocation, calculate_optimization_metrics

# Create sliders for weight adjustment
st.subheader("Optimization Weights")
cost_weight = st.slider(
    "Cost Weight (%)",
    min_value=0,
    max_value=100,
    value=70,  # Default 70%
    step=5,
    help="Higher values prioritize lower costs"
)

performance_weight = 100 - cost_weight  # Auto-calculate to sum to 100%

st.write(f"Performance Weight: {performance_weight}%")

# Run optimization
if st.button("Run Optimization"):
    optimized_data = optimize_allocation(
        data,
        strategy="linear_programming",
        cost_weight=cost_weight / 100,  # Convert to 0-1 scale
        performance_weight=performance_weight / 100
    )

    # Calculate and display metrics
    metrics = calculate_optimization_metrics(original_data, optimized_data)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "Cost Savings",
            f"${metrics['cost_savings']:,.2f}",
            f"{metrics['cost_savings_percent']:.1f}%"
        )
    with col2:
        st.metric(
            "Performance Change",
            f"{metrics['avg_performance_optimized']:.2%}",
            f"{metrics['performance_change_percent']:.1f}%"
        )
    with col3:
        st.metric(
            "Total Cost",
            f"${metrics['total_cost_optimized']:,.2f}"
        )

    # Display results
    st.dataframe(optimized_data)
```

### Advanced Usage with All Strategies

```python
from optimization import (
    optimize_allocation,
    optimize_carrier_allocation,  # Direct LP access
    allocate_to_cheapest_carrier,
    allocate_to_highest_performance,
)

# Compare multiple strategies
strategies = {
    "Balanced (70/30)": optimize_allocation(data, cost_weight=0.7, performance_weight=0.3),
    "Cost Focus (90/10)": optimize_allocation(data, cost_weight=0.9, performance_weight=0.1),
    "Performance Focus (30/70)": optimize_allocation(data, cost_weight=0.3, performance_weight=0.7),
    "Cheapest Only": allocate_to_cheapest_carrier(data),
    "Performance Only": allocate_to_highest_performance(data),
}

# Display comparison
for name, result in strategies.items():
    st.write(f"### {name}")
    st.dataframe(result)
```

## Linear Programming Algorithm

The linear programming optimization (`linear_programming.py`) uses the PuLP library to solve a constrained optimization problem:

### Objective Function

Minimize: `cost_weight × normalized_cost + performance_weight × (1 - normalized_performance)`

### Constraints

1. All containers in each lane/week/category must be allocated
2. Container allocation cannot be negative
3. Each carrier can only receive containers for lanes they serve

### Normalization

- Costs are normalized to 0-1 scale (lower cost = 0, higher cost = 1)
- Performance scores are normalized and inverted (higher performance = 0, lower performance = 1)
- This ensures fair comparison and weighting between metrics

### Process

1. Group data by lane, week, category, facility, port
2. For each group:
   - Normalize costs and performance within that group
   - Set up LP problem with decision variables (containers per carrier)
   - Add constraint: sum of allocations = total containers
   - Solve to minimize weighted objective
   - Assign containers based on solution

## Data Requirements

Input data must contain:

- `Dray SCAC(FL)`: Carrier identifier
- `Container Count`: Number of containers
- `Base Rate`: Cost per container
- `Performance_Score`: Performance metric (0-1 scale)
- Grouping columns: `Lane`, `Week Number`, `Category`, `Facility`, `Discharged Port`

## Default Weights

- **Cost Weight**: 70% (0.7) - Reflects typical business priority on cost savings
- **Performance Weight**: 30% (0.3) - Balances cost with service quality

These defaults can be adjusted via sliders or function parameters.

## Examples

### Example 1: Equal Weighting

```python
result = optimize_allocation(data, cost_weight=0.5, performance_weight=0.5)
```

### Example 2: Cost-Only (100%)

```python
result = optimize_allocation(data, cost_weight=1.0, performance_weight=0.0)
# Or use the dedicated function:
result = optimize_allocation(data, strategy="cheapest")
```

### Example 3: Performance-Only (100%)

```python
result = optimize_allocation(data, cost_weight=0.0, performance_weight=1.0)
# Or use the dedicated function:
result = optimize_allocation(data, strategy="performance")
```
