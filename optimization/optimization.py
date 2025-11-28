"""
Main Optimization Module - Orchestrates all optimization strategies

This module provides a unified interface to all carrier allocation strategies:
- Linear Programming (weighted cost/performance optimization)
- Highest performance carrier allocation

It serves as the main entry point for optimization operations.
"""
from __future__ import annotations

from typing import Literal
import pandas as pd

from .linear_programming import optimize_carrier_allocation as lp_optimize
from .performance_logic import allocate_to_highest_performance


OptimizationStrategy = Literal["linear_programming", "performance"]


def optimize_allocation(
    data: pd.DataFrame,
    strategy: OptimizationStrategy = "linear_programming",
    *,
    cost_weight: float = 0.7,
    performance_weight: float = 0.3,
    **kwargs
) -> pd.DataFrame:
    """
    Optimize carrier allocation using the specified strategy.
    
    This is the main entry point for all optimization operations. It routes
    to the appropriate optimization algorithm based on the strategy parameter.
    
    Parameters
    ----------
    data : pd.DataFrame
        Input data containing carrier options, costs, and performance metrics
    strategy : OptimizationStrategy
        The optimization strategy to use:
        - "linear_programming": Weighted optimization balancing cost and performance
        - "performance": Allocate all containers to the highest-performing carrier per lane
    cost_weight : float, default=0.7
        Weight for cost optimization (only used with linear_programming strategy)
        Value between 0 and 1. Higher values prioritize lower costs.
    performance_weight : float, default=0.3
        Weight for performance optimization (only used with linear_programming strategy)
        Value between 0 and 1. Higher values prioritize higher performance.
    **kwargs
        Additional keyword arguments passed to the specific optimization function
    
    Returns
    -------
    pd.DataFrame
        Optimized allocation with containers assigned to carriers
    
    Examples
    --------
    # Linear programming with custom weights
    >>> result = optimize_allocation(data, strategy="linear_programming", 
    ...                              cost_weight=0.8, performance_weight=0.2)
    
    # Highest performance allocation
    >>> result = optimize_allocation(data, strategy="performance")
    """
    if data is None or data.empty:
        return pd.DataFrame()
    
    if strategy == "linear_programming":
        return lp_optimize(
            data,
            cost_weight=cost_weight,
            performance_weight=performance_weight,
            **kwargs
        )
    
    elif strategy == "performance":
        return allocate_to_highest_performance(data, **kwargs)
    
    else:
        raise ValueError(
            f"Unknown strategy: {strategy}. "
            f"Valid options: 'linear_programming', 'performance'"
        )


def calculate_optimization_metrics(
    original_data: pd.DataFrame,
    optimized_data: pd.DataFrame,
) -> dict:
    """
    Calculate metrics comparing original allocation to optimized allocation.
    
    Parameters
    ----------
    original_data : pd.DataFrame
        Original carrier allocation
    optimized_data : pd.DataFrame
        Optimized carrier allocation
    
    Returns
    -------
    dict
        Dictionary containing comparison metrics:
        - total_cost_original: Total cost in original allocation
        - total_cost_optimized: Total cost in optimized allocation
        - cost_savings: Absolute cost savings
        - cost_savings_percent: Percentage cost savings
        - avg_performance_original: Average performance in original allocation
        - avg_performance_optimized: Average performance in optimized allocation
        - performance_change: Change in average performance
    """
    metrics = {}
    
    # Cost metrics
    if "Total Rate" in original_data.columns and "Total Rate" in optimized_data.columns:
        metrics["total_cost_original"] = original_data["Total Rate"].sum()
        metrics["total_cost_optimized"] = optimized_data["Total Rate"].sum()
        metrics["cost_savings"] = metrics["total_cost_original"] - metrics["total_cost_optimized"]
        
        if metrics["total_cost_original"] > 0:
            metrics["cost_savings_percent"] = (
                metrics["cost_savings"] / metrics["total_cost_original"] * 100
            )
        else:
            metrics["cost_savings_percent"] = 0
    
    # Performance metrics
    if "Performance_Score" in original_data.columns and "Performance_Score" in optimized_data.columns:
        # Weight by container count if available
        if "Container Count" in original_data.columns:
            orig_perf = (
                original_data["Performance_Score"] * original_data["Container Count"]
            ).sum() / original_data["Container Count"].sum()
            opt_perf = (
                optimized_data["Performance_Score"] * optimized_data["Container Count"]
            ).sum() / optimized_data["Container Count"].sum()
        else:
            orig_perf = original_data["Performance_Score"].mean()
            opt_perf = optimized_data["Performance_Score"].mean()
        
        metrics["avg_performance_original"] = orig_perf
        metrics["avg_performance_optimized"] = opt_perf
        metrics["performance_change"] = opt_perf - orig_perf
        metrics["performance_change_percent"] = (
            (metrics["performance_change"] / orig_perf * 100) if orig_perf > 0 else 0
        )
    
    return metrics


__all__ = [
    "optimize_allocation",
    "calculate_optimization_metrics",
    "lp_optimize",
    "allocate_to_cheapest_carrier",
    "allocate_to_highest_performance",
]
