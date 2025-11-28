"""
Optimization module for Carrier Tender Optimization Dashboard.

This module contains various optimization strategies for carrier allocation:
- Linear Programming optimization (cost vs performance trade-off)
- Cascading allocation (LP + historical volume constraints)
- Highest performance carrier allocation
- Historic volume analysis (carrier market share based on last 5 weeks)

Main entry point: optimize_allocation() - routes to the appropriate strategy
"""

from .optimization import (
    optimize_allocation,
    calculate_optimization_metrics,
)
from .linear_programming import optimize_carrier_allocation
from .cascading_logic import cascading_allocate_with_constraints
from .performance_logic import allocate_to_highest_performance
from .historic_volume import (
    calculate_carrier_volume_share,
    calculate_carrier_weekly_trends,
    get_carrier_lane_participation,
    filter_historical_weeks,
    get_last_n_weeks,
)
from .historic_volume_display import (
    show_historic_volume_analysis,
)

__all__ = [
    # Optimization strategies
    'optimize_allocation',
    'calculate_optimization_metrics',
    'optimize_carrier_allocation',
    'cascading_allocate_with_constraints',
    'allocate_to_highest_performance',
    # Historic volume analysis
    'calculate_carrier_volume_share',
    'calculate_carrier_weekly_trends',
    'get_carrier_lane_participation',
    'filter_historical_weeks',
    'get_last_n_weeks',
    'show_historic_volume_analysis',
]
