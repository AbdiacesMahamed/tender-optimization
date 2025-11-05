"""
Example Integration: Adding Linear Programming Optimization to Dashboard

This file shows how to integrate the optimization module with sliders
into your Streamlit dashboard. Add this code to your dashboard.py or 
create a new tab/section for optimization.
"""

import streamlit as st
import pandas as pd
from optimization import optimize_allocation, calculate_optimization_metrics


def show_optimization_interface(data: pd.DataFrame):
    """
    Display optimization interface with weight sliders and results.
    
    Parameters
    ----------
    data : pd.DataFrame
        The comprehensive data with carrier options, costs, and performance
    """
    st.header("🎯 Carrier Allocation Optimization")
    
    # Strategy selection
    st.subheader("1. Select Optimization Strategy")
    
    strategy = st.radio(
        "Choose your optimization approach:",
        options=["linear_programming", "cheapest", "performance"],
        format_func=lambda x: {
            "linear_programming": "⚖️ Balanced (Linear Programming)",
            "cheapest": "💰 Cost-Focused (Cheapest Carrier)",
            "performance": "⭐ Performance-Focused (Best Carrier)"
        }[x],
        horizontal=True
    )
    
    # Weight sliders (only show for linear programming)
    cost_weight = 0.7
    performance_weight = 0.3
    
    if strategy == "linear_programming":
        st.subheader("2. Adjust Optimization Weights")
        
        col1, col2 = st.columns(2)
        
        with col1:
            cost_weight_pct = st.slider(
                "💰 Cost Weight (%)",
                min_value=0,
                max_value=100,
                value=70,  # Default 70%
                step=5,
                help="Higher values prioritize lower costs. Recommended: 60-80% for most scenarios."
            )
            cost_weight = cost_weight_pct / 100
        
        with col2:
            # Auto-calculate performance weight
            performance_weight_pct = 100 - cost_weight_pct
            performance_weight = performance_weight_pct / 100
            
            st.metric(
                "⭐ Performance Weight (%)",
                f"{performance_weight_pct}%",
                help="Automatically calculated as 100% - Cost Weight"
            )
        
        # Visual representation of weights
        st.progress(cost_weight, text=f"Cost: {cost_weight:.0%} | Performance: {performance_weight:.0%}")
        
        # Interpretation guide
        with st.expander("📊 How to interpret these weights"):
            st.markdown("""
            **Weight Recommendations:**
            
            - **70/30 (Default)**: Balanced approach - saves costs while maintaining reasonable performance
            - **80/20**: Cost-focused - prioritizes savings, accepts some performance trade-offs
            - **60/40**: Performance-focused - willing to pay more for better service
            - **90/10**: Maximum savings - minimal consideration for performance
            - **50/50**: Equal priority - treats cost and performance equally
            
            **Use Cases:**
            - High-value shipments: Lower cost weight (50-60%)
            - Commodity shipments: Higher cost weight (70-90%)
            - Time-sensitive: Lower cost weight (40-60%)
            - Budget constraints: Higher cost weight (80-100%)
            """)
    
    # Run optimization button
    st.subheader("3. Run Optimization")
    
    if st.button("🚀 Optimize Allocation", type="primary", use_container_width=True):
        with st.spinner("Running optimization..."):
            try:
                # Run optimization
                optimized_data = optimize_allocation(
                    data,
                    strategy=strategy,
                    cost_weight=cost_weight,
                    performance_weight=performance_weight
                )
                
                # Calculate metrics
                metrics = calculate_optimization_metrics(data, optimized_data)
                
                # Store in session state
                st.session_state['optimized_data'] = optimized_data
                st.session_state['optimization_metrics'] = metrics
                
                st.success("✅ Optimization completed successfully!")
                
            except Exception as e:
                st.error(f"❌ Optimization failed: {str(e)}")
                return
    
    # Display results if optimization has been run
    if 'optimized_data' in st.session_state and 'optimization_metrics' in st.session_state:
        st.divider()
        st.subheader("4. Optimization Results")
        
        optimized_data = st.session_state['optimized_data']
        metrics = st.session_state['optimization_metrics']
        
        # Display metrics
        show_optimization_metrics(metrics)
        
        # Display comparison tables
        show_optimization_comparison(data, optimized_data)
        
        # Download button
        csv = optimized_data.to_csv(index=False)
        st.download_button(
            label="📥 Download Optimized Allocation",
            data=csv,
            file_name="optimized_carrier_allocation.csv",
            mime="text/csv",
            use_container_width=True
        )


def show_optimization_metrics(metrics: dict):
    """Display optimization metrics in a nice layout."""
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if 'cost_savings' in metrics:
            st.metric(
                "💰 Cost Savings",
                f"${metrics['cost_savings']:,.2f}",
                f"{metrics.get('cost_savings_percent', 0):.1f}%",
                delta_color="normal"
            )
    
    with col2:
        if 'total_cost_optimized' in metrics:
            st.metric(
                "💵 Optimized Cost",
                f"${metrics['total_cost_optimized']:,.2f}",
                help="Total cost after optimization"
            )
    
    with col3:
        if 'avg_performance_optimized' in metrics:
            st.metric(
                "⭐ Avg Performance",
                f"{metrics['avg_performance_optimized']:.1%}",
                f"{metrics.get('performance_change_percent', 0):+.1f}%",
                delta_color="normal"
            )
    
    with col4:
        if 'total_cost_original' in metrics and 'total_cost_optimized' in metrics:
            roi = (metrics['cost_savings'] / metrics['total_cost_original'] * 100) if metrics['total_cost_original'] > 0 else 0
            st.metric(
                "📈 ROI",
                f"{roi:.1f}%",
                help="Return on Investment"
            )


def show_optimization_comparison(original_data: pd.DataFrame, optimized_data: pd.DataFrame):
    """Show side-by-side comparison of original vs optimized allocation."""
    
    st.subheader("Allocation Comparison")
    
    tab1, tab2, tab3 = st.tabs(["📊 Summary", "📋 Original Allocation", "✨ Optimized Allocation"])
    
    with tab1:
        # Summary statistics
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Original Allocation**")
            st.dataframe(
                original_data.groupby('Dray SCAC(FL)').agg({
                    'Container Count': 'sum',
                    'Total Rate': 'sum',
                    'Performance_Score': 'mean'
                }).round(2),
                use_container_width=True
            )
        
        with col2:
            st.markdown("**Optimized Allocation**")
            st.dataframe(
                optimized_data.groupby('Dray SCAC(FL)').agg({
                    'Container Count': 'sum',
                    'Total Rate': 'sum',
                    'Performance_Score': 'mean'
                }).round(2),
                use_container_width=True
            )
    
    with tab2:
        st.dataframe(original_data, use_container_width=True, height=400)
    
    with tab3:
        st.dataframe(optimized_data, use_container_width=True, height=400)


# =============================================================================
# HOW TO INTEGRATE INTO YOUR DASHBOARD
# =============================================================================

"""
To integrate this into your dashboard.py file:

1. Import the function:
   ```python
   from optimization_example import show_optimization_interface
   ```

2. Add a new tab or section:
   ```python
   tab_optimization = st.tabs(["Current View", "Analytics", "Optimization"])
   
   with tab_optimization:
       show_optimization_interface(comprehensive_data)
   ```

3. Or add it as a sidebar option:
   ```python
   with st.sidebar:
       if st.checkbox("Show Optimization"):
           show_optimization_interface(comprehensive_data)
   ```

4. Make sure your data has the required columns:
   - Dray SCAC(FL) (carrier)
   - Container Count
   - Base Rate (or CPC)
   - Performance_Score
   - Lane, Week Number, Category, Facility, Discharged Port
"""
