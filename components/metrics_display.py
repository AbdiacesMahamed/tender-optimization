"""
Metrics display module — renders the 4 cost-strategy cards on the dashboard.

Extracted from metrics.py so the pure-display logic is isolated from
data calculation and scenario orchestration.
"""
import streamlit as st
from .config_styling import section_header
from .utils import get_rate_columns


def display_current_metrics(metrics, constrained_data=None, unconstrained_data=None):
    """Display main metrics dashboard
    
    Args:
        metrics: Dictionary containing calculated metrics
        constrained_data: DataFrame containing constrained/locked containers (optional)
        unconstrained_data: DataFrame containing unconstrained containers (optional)
    """
    if metrics is None:
        st.warning("⚠️ No data matches your selection.")
        return
    
    # Determine if constraints are active
    has_constraints = (
        constrained_data is not None 
        and len(constrained_data) > 0 
        and unconstrained_data is not None
    )
    
    # Get rate columns for cost calculations
    rate_cols = get_rate_columns()
    
    # Calculate constrained cost once if constraints are active
    constrained_cost = 0
    if has_constraints:
        constrained_cost = constrained_data[rate_cols['total_rate']].sum()
    
    # Get current rate type for display
    rate_type = st.session_state.get('rate_type', 'Base Rate')
    rate_type_label = f"({rate_type})" if rate_type == 'CPC' else ""
    
    section_header(f"📊 Cost Analysis Dashboard {rate_type_label}")
    
    # Cost comparison cards - now showing 4 strategies
    st.markdown(f"### 💰 Cost Strategy Comparison {rate_type_label}")
    col1, col2, col3, col4 = st.columns(4)
    
    # Current Selection - sum constrained + unconstrained costs
    with col1:
        if has_constraints:
            unconstrained_current_cost = unconstrained_data[rate_cols['total_rate']].sum()
            total_current_cost = constrained_cost + unconstrained_current_cost
        else:
            total_current_cost = metrics['total_cost']
        
        st.markdown(f"""
        <div style="background-color: #f0f2f6; padding: 15px; border-radius: 10px;">
            <h4 style="color: #1f77b4; margin: 0;">📋 Current</h4>
            <h2 style="color: #1f77b4; margin: 5px 0;">${total_current_cost:,.2f}</h2>
            <p style="margin: 0; color: #666;">Your selections</p>
        </div>
        """, unsafe_allow_html=True)
    
    # Performance scenario (calculated based on highest performance carriers)
    with col2:
        _render_performance_card(metrics, total_current_cost, constrained_cost, has_constraints)
    
    # Cheapest Cost scenario
    with col3:
        _render_cheapest_card(metrics, total_current_cost, constrained_cost, has_constraints)
    
    # Optimized scenario (calculated using cascading logic with LP + historical constraints)
    with col4:
        _render_optimized_card(metrics, total_current_cost, constrained_cost, has_constraints)
    
    st.markdown("---")


# ---------------------------------------------------------------------------
# Private card renderers
# ---------------------------------------------------------------------------

def _render_performance_card(metrics, total_current_cost, constrained_cost, has_constraints):
    if metrics.get('performance_cost') is not None:
        perf_cost = constrained_cost + metrics['performance_cost'] if has_constraints else metrics['performance_cost']
        perf_diff = perf_cost - total_current_cost
        perf_diff_pct = (perf_diff / total_current_cost * 100) if total_current_cost > 0 else 0
        
        if perf_diff > 0:
            diff_text = f"Cost ${perf_diff:,.2f} more ({perf_diff_pct:+.1f}%)"
            diff_color = "#ff6b6b"
        elif perf_diff < 0:
            diff_text = f"Save ${abs(perf_diff):,.2f} ({abs(perf_diff_pct):.1f}%)"
            diff_color = "#28a745"
        else:
            diff_text = "Same as current"
            diff_color = "#666"
        
        st.markdown(f"""
        <div style="background-color: #fff0e6; padding: 15px; border-radius: 10px;">
            <h4 style="color: #ff8c00; margin: 0;">🏆 Performance</h4>
            <h2 style="color: #ff8c00; margin: 5px 0;">${perf_cost:,.2f}</h2>
            <p style="margin: 0; color: {diff_color};">{diff_text}</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background-color: #fff0e6; padding: 15px; border-radius: 10px;">
            <h4 style="color: #ff8c00; margin: 0;">🏆 Performance</h4>
            <h2 style="color: #ff8c00; margin: 5px 0;">N/A</h2>
            <p style="margin: 0; color: #ff8c00;">No performance data<br><small>Performance scores needed</small></p>
        </div>
        """, unsafe_allow_html=True)


def _render_cheapest_card(metrics, total_current_cost, constrained_cost, has_constraints):
    if metrics.get('cheapest_cost') is not None:
        cheap_cost = constrained_cost + metrics['cheapest_cost'] if has_constraints else metrics['cheapest_cost']
        cheap_diff = cheap_cost - total_current_cost
        cheap_diff_pct = (cheap_diff / total_current_cost * 100) if total_current_cost > 0 else 0
        
        if cheap_diff > 0:
            diff_text = f"Cost ${cheap_diff:,.2f} more ({cheap_diff_pct:+.1f}%)"
            diff_color = "#ff6b6b"
        elif cheap_diff < 0:
            diff_text = f"Save ${abs(cheap_diff):,.2f} ({abs(cheap_diff_pct):.1f}%)"
            diff_color = "#28a745"
        else:
            diff_text = "Same as current"
            diff_color = "#666"
        
        st.markdown(f"""
        <div style="background-color: #e8f5e9; padding: 15px; border-radius: 10px;">
            <h4 style="color: #28a745; margin: 0;">💰 Cheapest</h4>
            <h2 style="color: #28a745; margin: 5px 0;">${cheap_cost:,.2f}</h2>
            <p style="margin: 0; color: {diff_color};">{diff_text}</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="background-color: #e8f5e9; padding: 15px; border-radius: 10px;">
            <h4 style="color: #28a745; margin: 0;">💰 Cheapest</h4>
            <h2 style="color: #28a745; margin: 5px 0;">N/A</h2>
            <p style="margin: 0; color: #28a745;">No rate data<br><small>Valid rates needed</small></p>
        </div>
        """, unsafe_allow_html=True)


def _render_optimized_card(metrics, total_current_cost, constrained_cost, has_constraints):
    if metrics.get('optimized_cost') is not None:
        opt_cost = constrained_cost + metrics['optimized_cost'] if has_constraints else metrics['optimized_cost']
        opt_diff = opt_cost - total_current_cost
        opt_diff_pct = (opt_diff / total_current_cost * 100) if total_current_cost > 0 else 0
        
        # Get current slider settings for display
        cost_pct = st.session_state.get('opt_cost_weight', 70)
        perf_pct = st.session_state.get('opt_performance_weight', 30)
        growth_pct = st.session_state.get('opt_max_growth_pct', 30)
        
        if opt_diff > 0:
            diff_text = f"Cost ${opt_diff:,.2f} more ({opt_diff_pct:+.1f}%)"
            diff_color = "#ff6b6b"
        elif opt_diff < 0:
            diff_text = f"Save ${abs(opt_diff):,.2f} ({abs(opt_diff_pct):.1f}%)"
            diff_color = "#28a745"
        else:
            diff_text = "Matches current selections"
            diff_color = "#666"
        
        st.markdown(f"""
        <div style="background-color: #e6f7ff; padding: 15px; border-radius: 10px;">
            <h4 style="color: #17a2b8; margin: 0;">🧮 Optimized</h4>
            <h2 style="color: #17a2b8; margin: 5px 0;">${opt_cost:,.2f}</h2>
            <p style="margin: 0; color: {diff_color};">{diff_text}<br><small>{cost_pct}/{perf_pct} • {growth_pct}% cap</small></p>
        </div>
        """, unsafe_allow_html=True)
    else:
        opt_error = st.session_state.get('_optimization_error', 'Need historical data')
        st.markdown(f"""
        <div style="background-color: #e6f7ff; padding: 15px; border-radius: 10px;">
            <h4 style="color: #17a2b8; margin: 0;">🧮 Optimized</h4>
            <h2 style="color: #17a2b8; margin: 5px 0;">N/A</h2>
            <p style="margin: 0; color: #17a2b8;">Optimization unavailable<br><small>{opt_error}</small></p>
        </div>
        """, unsafe_allow_html=True)
