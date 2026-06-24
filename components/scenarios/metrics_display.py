"""
Metrics display module — renders the 4 cost-strategy cards on the dashboard.

Extracted from metrics.py so the pure-display logic is isolated from
data calculation and scenario orchestration.
"""
import streamlit as st
import pandas as pd
from ..core.config_styling import section_header
from ..core.utils import get_rate_columns


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

    # Show insight when Performance is cheaper than Optimized
    _show_performance_vs_optimized_insight(metrics, has_constraints, constrained_cost)

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


def _show_performance_vs_optimized_insight(metrics, has_constraints, constrained_cost):
    """Show an expandable insight when the Performance scenario is cheaper than Optimized."""
    perf_cost = metrics.get('performance_cost')
    opt_cost = metrics.get('optimized_cost')

    if perf_cost is None or opt_cost is None:
        return
    if perf_cost >= opt_cost:
        return

    saving = opt_cost - perf_cost
    saving_pct = (saving / opt_cost * 100) if opt_cost > 0 else 0

    # Get cached allocated DataFrames for group-level comparison
    perf_data = st.session_state.get('_cached_perf_allocated')
    opt_data = st.session_state.get('_cached_opt_allocated')

    st.markdown(
        f"""<div style="background-color: #fff3cd; padding: 12px 16px; border-radius: 8px; border-left: 4px solid #ff8c00; margin-top: 12px;">
        <strong>Performance is ${saving:,.0f} cheaper than Optimized ({saving_pct:.1f}% less)</strong>
        </div>""",
        unsafe_allow_html=True,
    )

    if perf_data is None or opt_data is None or perf_data.empty or opt_data.empty:
        return

    rate_cols = get_rate_columns()
    carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in perf_data.columns else 'Carrier'
    group_cols = [c for c in ['Category', 'Lane', 'Week Number'] if c in perf_data.columns and c in opt_data.columns]

    if not group_cols:
        return

    # Aggregate cost per group for each strategy
    perf_grouped = perf_data.groupby(group_cols, as_index=False).agg(
        perf_total_cost=(rate_cols['total_rate'], 'sum'),
        perf_containers=('Container Count', 'sum'),
        perf_carrier=(carrier_col, 'first'),
    )
    opt_grouped = opt_data.groupby(group_cols, as_index=False).agg(
        opt_total_cost=(rate_cols['total_rate'], 'sum'),
        opt_containers=('Container Count', 'sum'),
        opt_carrier=(carrier_col, 'first'),
    )

    comparison = perf_grouped.merge(opt_grouped, on=group_cols, how='inner')
    comparison['cost_diff'] = comparison['perf_total_cost'] - comparison['opt_total_cost']

    # Groups where performance is cheaper (negative diff)
    perf_wins = comparison[comparison['cost_diff'] < -0.01].copy()
    perf_wins = perf_wins.sort_values('cost_diff')

    if perf_wins.empty:
        return

    with st.expander(f"Why is Performance cheaper? ({len(perf_wins)} groups where Performance wins)", expanded=False):
        st.markdown("""
**Root causes** (most common reasons):
1. **High-performer is also the cheapest carrier** in that lane — Performance picks them for quality, but it also happens to be the lowest rate
2. **Growth constraints** in the Optimizer force volume to more expensive carriers to stay within 130% of historical allocation
3. **Carrier diversity** — the Optimizer spreads volume across multiple carriers; Performance concentrates on one (often cheaper) carrier
        """)

        # Show top groups
        display_cols = group_cols + ['perf_carrier', 'perf_total_cost', 'opt_carrier', 'opt_total_cost', 'cost_diff']
        show_df = perf_wins[display_cols].head(15).copy()
        show_df.columns = group_cols + ['Perf Carrier', 'Perf Cost', 'Opt Carrier', 'Opt Cost', 'Difference']
        show_df['Perf Cost'] = show_df['Perf Cost'].apply(lambda x: f"${x:,.0f}")
        show_df['Opt Cost'] = show_df['Opt Cost'].apply(lambda x: f"${x:,.0f}")
        show_df['Difference'] = show_df['Difference'].apply(lambda x: f"-${abs(x):,.0f}")

        st.dataframe(show_df, use_container_width=True, hide_index=True)

        total_perf_saving = abs(perf_wins['cost_diff'].sum())
        st.markdown(f"**Total saving from these {len(perf_wins)} groups: ${total_perf_saving:,.0f}**")

        # Identify the most common reason
        same_carrier_mask = perf_wins['perf_carrier'] == perf_wins['opt_carrier']
        same_carrier_count = same_carrier_mask.sum()
        diff_carrier_count = len(perf_wins) - same_carrier_count

        if diff_carrier_count > same_carrier_count:
            st.info(
                f"In **{diff_carrier_count}/{len(perf_wins)}** groups, Performance picked a different (cheaper) carrier "
                f"than Optimized. This usually means the Optimizer's growth cap or diversity constraints "
                f"forced volume to a more expensive carrier."
            )
        else:
            st.info(
                f"In **{same_carrier_count}/{len(perf_wins)}** groups, both picked the same carrier but "
                f"Performance allocated more volume to them (concentrating vs. spreading). "
                f"The Optimizer splits volume across carriers to limit risk."
            )


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
