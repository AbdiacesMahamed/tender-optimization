"""
Metrics and KPI calculation module for the Carrier Tender Optimization Dashboard.

This is the orchestrator — calculation lives here, display and strategy logic
are delegated to focused modules:
  - metrics_display.py   → cost-card rendering
  - scenario_strategies.py → Current / Optimized / Performance / Cheapest
  - peel_pile.py          → peel pile analysis + constraints
"""
import logging
import streamlit as st
import pandas as pd
import numpy as np
from .config_styling import section_header
from .utils import (
    get_rate_columns, safe_numeric, format_currency, format_percentage,
    get_grouping_columns, count_containers, parse_container_ids,
    concat_and_dedupe_containers, filter_excluded_carrier_facility_rows
)
from optimization.performance_logic import allocate_to_highest_performance
from .container_tracer import add_detailed_carrier_flips_column, get_container_movement_summary

# Re-export from new modules so existing imports keep working
from .metrics_display import display_current_metrics          # noqa: F401
from .peel_pile import (                                      # noqa: F401
    show_peel_pile_analysis,
    apply_peel_pile_as_constraints,
)

logger = logging.getLogger(__name__)


# ==================== HELPER FUNCTIONS ====================

def add_carrier_flips_column(current_data, original_data, carrier_col='Dray SCAC(FL)'):
    """
    Add 'Carrier Flips' column showing allocation changes per carrier in each group.
    """
    if original_data is None or original_data.empty:
        current_data['Carrier Flips'] = 'No baseline'
        return current_data
    
    group_cols = get_grouping_columns(
        current_data, 
        base_cols=['Discharged Port', 'Lane', 'Facility', 'Week Number']
    )
    
    if not group_cols:
        current_data['Carrier Flips'] = 'No groups'
        return current_data
    
    # Build original state: {group_key: {carrier: count}}
    original_state = {}
    for _, row in original_data.iterrows():
        key = tuple(row.get(col, '') for col in group_cols)
        carrier = row.get(carrier_col, 'Unknown')
        count = row.get('Container Count', 0)
        if key not in original_state:
            original_state[key] = {}
        original_state[key][carrier] = original_state[key].get(carrier, 0) + count
    
    flips = []
    for _, row in current_data.iterrows():
        key = tuple(row.get(col, '') for col in group_cols)
        curr_carrier = row.get(carrier_col, 'Unknown')
        curr_count = row.get('Container Count', 0)
        
        if key not in original_state:
            flips.append("🆕 New group")
            continue
        
        orig_group = original_state[key]
        orig_own_count = orig_group.get(curr_carrier, 0)
        
        if orig_own_count == 0:
            orig_carriers = [c for c, cnt in orig_group.items() if cnt > 0]
            if len(orig_carriers) == 0:
                flips.append(f"🔄 New: {curr_count:.0f}")
            elif len(orig_carriers) == 1:
                flips.append(f"🔄 New: {curr_count:.0f} (was {orig_carriers[0]})")
            elif len(orig_carriers) <= 3:
                flips.append(f"🔄 New: {curr_count:.0f} (was {', '.join(orig_carriers)})")
            else:
                flips.append(f"🔄 New: {curr_count:.0f} (was {len(orig_carriers)} carriers)")
        else:
            diff = curr_count - orig_own_count
            if abs(diff) < 0.5:
                flips.append(f"✓ Kept {orig_own_count:.0f}")
            elif diff > 0:
                flips.append(f"✓ Had {orig_own_count:.0f}, now {curr_count:.0f} (+{diff:.0f})")
            else:
                flips.append(f"✓ Had {orig_own_count:.0f}, now {curr_count:.0f} ({diff:.0f})")
    
    current_data['Carrier Flips'] = flips
    return current_data


def add_missing_rate_rows(display_data, source_data, carrier_col='Dray SCAC(FL)'):
    """Add back rows for missing rate data, preserving carrier information."""
    if 'Missing_Rate' not in source_data.columns:
        return display_data
    
    missing_rate_rows = source_data[source_data['Missing_Rate'] == True]
    if len(missing_rate_rows) == 0:
        return display_data
    
    missing_rate_rows = missing_rate_rows.copy()
    group_cols = get_grouping_columns(missing_rate_rows)
    if carrier_col in missing_rate_rows.columns and carrier_col not in group_cols:
        group_cols.append(carrier_col)
    
    agg_dict = {col: 'first' for col in missing_rate_rows.columns if col not in group_cols}
    agg_dict['Container Count'] = 'sum'
    agg_dict['Container Numbers'] = lambda x: ', '.join(str(v) for v in x if pd.notna(v))
    
    missing_rate_rows = missing_rate_rows.groupby(group_cols, as_index=False).agg(agg_dict)
    
    rate_cols_list = ['Base Rate', 'Total Rate', 'Performance_Score', 'CPC', 'Total CPC']
    for col in rate_cols_list:
        if col in missing_rate_rows.columns:
            missing_rate_rows[col] = None if col in ['Base Rate', 'Performance_Score', 'CPC'] else 0
    
    return pd.concat([display_data, missing_rate_rows], ignore_index=True)


# ==================== METRICS CALCULATION ====================

def calculate_enhanced_metrics(data, unconstrained_data=None, max_constrained_carriers=None,
                               carrier_facility_exclusions=None, full_unfiltered_data=None):
    """Calculate comprehensive metrics for the dashboard."""
    if data is None or len(data) == 0:
        return None
    
    historical_data_source = full_unfiltered_data if full_unfiltered_data is not None else data
    rate_cols = get_rate_columns()
    total_containers_all = data['Container Count'].sum()
    data_with_rates = data.copy()
    scenario_data = unconstrained_data.copy() if unconstrained_data is not None else data_with_rates.copy()
    
    if max_constrained_carriers is None:
        max_constrained_carriers = []
    if carrier_facility_exclusions is None:
        carrier_facility_exclusions = {}

    # Basic metrics
    if rate_cols['total_rate'] in data_with_rates.columns:
        total_cost = data_with_rates[rate_cols['total_rate']].fillna(0).sum()
    else:
        total_cost = 0
    total_containers_with_rates = data_with_rates['Container Count'].sum()
    unique_carriers = data['Dray SCAC(FL)'].nunique() if 'Dray SCAC(FL)' in data.columns else 0
    unique_lanes = data['Lane'].nunique() if 'Lane' in data.columns else 0
    unique_ports = data['Discharged Port'].nunique() if 'Discharged Port' in data.columns else 0
    unique_facilities = data['Facility'].nunique() if 'Facility' in data.columns else 0
    avg_rate = total_cost / total_containers_with_rates if total_containers_with_rates > 0 else 0
    avg_performance = data_with_rates['Performance_Score'].mean() if 'Performance_Score' in data_with_rates.columns else None

    # --- Performance scenario cost ---
    performance_cost = _calc_performance_cost(scenario_data, carrier_facility_exclusions, rate_cols)

    # --- Cheapest cost scenario ---
    cheapest_cost = _calc_cheapest_cost(scenario_data, carrier_facility_exclusions, rate_cols)

    # --- Optimized cost scenario ---
    optimized_cost = _calc_optimized_cost(
        scenario_data, carrier_facility_exclusions, max_constrained_carriers,
        historical_data_source, rate_cols,
    )

    # Fallback
    if optimized_cost is None and len(scenario_data) > 0:
        if rate_cols['total_rate'] in scenario_data.columns:
            fallback_cost = scenario_data[rate_cols['total_rate']].fillna(0).sum()
            if fallback_cost > 0:
                optimized_cost = fallback_cost
                st.session_state['_cached_opt_allocated'] = scenario_data.copy()

    return {
        'total_cost': total_cost,
        'total_containers': total_containers_all,
        'unique_carriers': unique_carriers,
        'unique_scacs': unique_carriers,
        'unique_lanes': unique_lanes,
        'unique_ports': unique_ports,
        'unique_facilities': unique_facilities,
        'avg_rate': avg_rate,
        'avg_performance': avg_performance,
        'performance_cost': performance_cost,
        'cheapest_cost': cheapest_cost,
        'optimized_cost': optimized_cost,
    }


# ---------------------------------------------------------------------------
# calculate_enhanced_metrics helpers (private)
# ---------------------------------------------------------------------------

def _calc_performance_cost(scenario_data, carrier_facility_exclusions, rate_cols):
    if 'Performance_Score' not in scenario_data.columns or len(scenario_data) == 0:
        return None
    try:
        carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in scenario_data.columns else 'Carrier'
        filtered = filter_excluded_carrier_facility_rows(scenario_data.copy(), carrier_facility_exclusions, carrier_col)
        has_valid_rate = filtered['Base Rate'].notna() & (filtered['Base Rate'] != 0)
        rated_perf = filtered[has_valid_rate].copy()
        unrated_perf = filtered[~has_valid_rate].copy()
        allocated = allocate_to_highest_performance(
            rated_perf, carrier_column=carrier_col, container_column='Container Count',
            performance_column='Performance_Score', container_numbers_column='Container Numbers',
        )
        if len(unrated_perf) > 0:
            allocated = pd.concat([allocated, unrated_perf], ignore_index=True)
        cost = allocated[rate_cols['total_rate']].sum() if rate_cols['total_rate'] in allocated.columns else None
        st.session_state['_cached_perf_allocated'] = allocated
        return cost
    except (ValueError, KeyError):
        return None


def _calc_cheapest_cost(scenario_data, carrier_facility_exclusions, rate_cols):
    if len(scenario_data) == 0:
        return None
    try:
        carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in scenario_data.columns else 'Carrier'
        working = filter_excluded_carrier_facility_rows(scenario_data.copy(), carrier_facility_exclusions, carrier_col)
        working[rate_cols['rate']] = pd.to_numeric(working[rate_cols['rate']], errors='coerce')
        working['Container Count'] = pd.to_numeric(working['Container Count'], errors='coerce').fillna(0)
        working = working[working[rate_cols['rate']].notna()]
        if len(working) == 0:
            return None
        group_cols = [col for col in ['Category', 'Lane', 'Week Number'] if col in working.columns]
        if not group_cols:
            return None
        working = working.sort_values(rate_cols['rate'], ascending=True)
        cheapest_per_group = working.groupby(group_cols, as_index=False).first()
        if 'Container Numbers' in working.columns:
            cn_concat = (
                working.groupby(group_cols)['Container Numbers']
                .apply(concat_and_dedupe_containers)
                .reset_index(name='_cn_all')
            )
            cheapest_per_group = cheapest_per_group.merge(cn_concat, on=group_cols, how='left')
            cheapest_per_group['Container Count'] = cheapest_per_group['_cn_all'].apply(count_containers)
        else:
            container_totals = working.groupby(group_cols)['Container Count'].sum()
            cheapest_per_group = cheapest_per_group.set_index(group_cols)
            cheapest_per_group['Container Count'] = container_totals
            cheapest_per_group = cheapest_per_group.reset_index()
        cheapest_per_group['Total Cost'] = cheapest_per_group[rate_cols['rate']] * cheapest_per_group['Container Count']
        return cheapest_per_group['Total Cost'].sum()
    except (ValueError, KeyError):
        return None


def _calc_optimized_cost(scenario_data, carrier_facility_exclusions,
                         max_constrained_carriers, historical_data_source, rate_cols):
    if len(scenario_data) == 0:
        return None
    try:
        from optimization import cascading_allocate_with_constraints
        carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in scenario_data.columns else 'Carrier'
        optimization_source = filter_excluded_carrier_facility_rows(scenario_data.copy(), carrier_facility_exclusions, carrier_col)
        if 'Container Numbers' in optimization_source.columns:
            optimization_source['Container Count'] = optimization_source['Container Numbers'].apply(count_containers)
        has_valid_rate = optimization_source['Base Rate'].notna() & (optimization_source['Base Rate'] != 0)
        rated_data = optimization_source[has_valid_rate].copy()
        unrated_data = optimization_source[~has_valid_rate].copy()
        cost_weight = st.session_state.get('opt_cost_weight', 70) / 100.0
        performance_weight = st.session_state.get('opt_performance_weight', 30) / 100.0
        max_growth_pct = st.session_state.get('opt_max_growth_pct', 30) / 100.0
        optimized_allocated = None
        if len(rated_data) > 0:
            optimized_allocated = cascading_allocate_with_constraints(
                rated_data, max_growth_pct=max_growth_pct, cost_weight=cost_weight,
                performance_weight=performance_weight, n_historical_weeks=5,
                carrier_column=carrier_col, container_column='Container Count',
                excluded_carriers=max_constrained_carriers, historical_data=historical_data_source,
            )
        if optimized_allocated is not None and len(optimized_allocated) > 0:
            if len(unrated_data) > 0:
                optimized_allocated = pd.concat([optimized_allocated, unrated_data], ignore_index=True)
            cost = optimized_allocated[rate_cols['total_rate']].sum() if rate_cols['total_rate'] in optimized_allocated.columns else None
            st.session_state['_cached_opt_allocated'] = optimized_allocated
            return cost
        return None
    except Exception as e:
        import traceback
        logger.warning(f"Optimization failed: {e}\n{traceback.format_exc()}")
        st.session_state['_optimization_error'] = f"{type(e).__name__}: {e}"
        return None


# ==================== DETAILED ANALYSIS TABLE (ORCHESTRATOR) ====================

def show_detailed_analysis_table(final_filtered_data, unconstrained_data, constrained_data,
                                  metrics=None, max_constrained_carriers=None,
                                  carrier_facility_exclusions=None, full_unfiltered_data=None):
    """Show detailed analysis table — delegates strategy logic to scenario_strategies.py."""
    from .scenario_strategies import (
        apply_current_selection, apply_optimized_strategy,
        apply_performance_strategy, apply_cheapest_strategy,
    )

    section_header("📋 Detailed Analysis Table")

    historical_data_source = full_unfiltered_data if full_unfiltered_data is not None else final_filtered_data
    if max_constrained_carriers is None:
        max_constrained_carriers = []
    if carrier_facility_exclusions is None:
        carrier_facility_exclusions = {}
    if metrics is None:
        metrics = calculate_enhanced_metrics(final_filtered_data)
    if metrics is None:
        st.warning("⚠️ No data available for analysis.")
        return

    has_constraints = len(constrained_data) > 0 if isinstance(constrained_data, pd.DataFrame) else False
    rate_cols = get_rate_columns()
    carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in final_filtered_data.columns else 'Carrier'

    if not has_constraints:
        st.info("ℹ️ **No constraints active** - All containers in the table below can be manipulated by scenarios")

    # Strategy selector
    selected = st.selectbox("📊 Select Strategy:", ['Current Selection', 'Performance', 'Cheapest Cost', 'Optimized'])
    if selected != 'Performance':
        st.session_state.pop('_cached_perf_allocated', None)
    if selected != 'Optimized':
        st.session_state.pop('_cached_opt_allocated', None)

    # Show constrained section (common to all strategies)
    constrained_download_data = None
    if has_constraints:
        constrained_download_data = _render_constrained_section(
            constrained_data, unconstrained_data, final_filtered_data,
            rate_cols, carrier_col, selected,
        )

    # Prepare working data
    display_data_raw = unconstrained_data.copy() if has_constraints else final_filtered_data.copy()
    if 'Container Numbers' in display_data_raw.columns and 'Container Count' not in display_data_raw.columns:
        display_data_raw['Container Count'] = display_data_raw['Container Numbers'].apply(count_containers)
    elif 'Container Count' not in display_data_raw.columns:
        display_data_raw['Container Count'] = 0

    display_data_with_rates = display_data_raw.copy()
    if 'Container Numbers' in display_data_with_rates.columns:
        _actual = display_data_with_rates['Container Numbers'].apply(count_containers).sum()
        if _actual != int(display_data_with_rates['Container Count'].sum()):
            display_data_with_rates['Container Count'] = display_data_with_rates['Container Numbers'].apply(count_containers)
            if 'Base Rate' in display_data_with_rates.columns:
                display_data_with_rates['Total Rate'] = display_data_with_rates['Base Rate'] * display_data_with_rates['Container Count']
            if 'CPC' in display_data_with_rates.columns:
                display_data_with_rates['Total CPC'] = display_data_with_rates['CPC'] * display_data_with_rates['Container Count']

    baseline_data = display_data_with_rates.copy()

    # ---- Dispatch to strategy ----
    performance_reallocated = 0
    performance_groups_impacted = 0

    if selected == 'Cheapest Cost':
        source = unconstrained_data.copy() if has_constraints else final_filtered_data.copy()
        display_data, download_data, desc, filename, rate_cols = apply_cheapest_strategy(
            source, carrier_col, carrier_facility_exclusions,
            has_constraints, constrained_data, metrics,
            final_filtered_data, unconstrained_data,
        )
    else:
        # Current Selection / Performance / Optimized share the same column pipeline
        if selected == 'Current Selection':
            display_data, performance_reallocated, performance_groups_impacted = apply_current_selection(
                display_data_with_rates, carrier_col, max_constrained_carriers,
            )
        elif selected == 'Optimized':
            display_data, performance_reallocated, performance_groups_impacted = apply_optimized_strategy(
                display_data_with_rates, carrier_col, max_constrained_carriers,
                carrier_facility_exclusions, historical_data_source,
            )
        elif selected == 'Performance':
            display_data, performance_reallocated, performance_groups_impacted = apply_performance_strategy(
                display_data_with_rates, carrier_col, carrier_facility_exclusions,
            )

        # Carrier Flips (common to non-cheapest strategies)
        display_data = add_detailed_carrier_flips_column(display_data, baseline_data, carrier_col=carrier_col)
        if 'Carrier Flips (Detailed)' in display_data.columns:
            display_data.rename(columns={'Carrier Flips (Detailed)': 'Carrier Flips'}, inplace=True)

        # Column selection & renaming
        display_data, download_data, desc, filename = _build_columns_and_description(
            display_data, selected, carrier_col, rate_cols, metrics,
            has_constraints, constrained_data, unconstrained_data,
            performance_reallocated, performance_groups_impacted,
        )

    # ---- Render table ----
    st.info(desc)
    display_formatted = _format_display(display_data, rate_cols)
    st.dataframe(display_formatted, use_container_width=True, hide_index=True)

    # Metrics row
    _render_table_metrics(display_data, has_constraints, rate_cols)

    # Downloads
    csv = download_data.to_csv(index=False)
    label_suffix = " (Unconstrained)" if has_constraints else ""
    download_filename = f"unconstrained_{filename}" if has_constraints else filename
    st.download_button(label=f"📥 Download {selected}{label_suffix}", data=csv,
                       file_name=download_filename, mime='text/csv', use_container_width=True)
    if has_constraints and constrained_download_data is not None:
        st.download_button(label="📥 Download Constrained Allocations",
                           data=constrained_download_data.to_csv(index=False),
                           file_name='constrained_allocations.csv', mime='text/csv',
                           use_container_width=True, key='download_constrained')

    # Peel pile
    show_peel_pile_analysis(final_filtered_data)


# ---------------------------------------------------------------------------
# show_detailed_analysis_table helpers (private)
# ---------------------------------------------------------------------------

def _render_constrained_section(constrained_data, unconstrained_data,
                                final_filtered_data, rate_cols, carrier_col, selected):
    """Render the constrained-allocations table. Returns download_data."""
    if 'Container Numbers' in constrained_data.columns:
        constrained_containers = constrained_data['Container Numbers'].apply(count_containers).sum()
    else:
        constrained_containers = constrained_data['Container Count'].sum()
    if 'Container Numbers' in unconstrained_data.columns:
        unconstrained_containers = unconstrained_data['Container Numbers'].apply(count_containers).sum()
    else:
        unconstrained_containers = unconstrained_data['Container Count'].sum()

    st.info(f"""
    🔒 **Constraints Active:** 
    - {constrained_containers:,} containers locked by constraints
    - {unconstrained_containers:,} containers available for optimization
    - Total: {constrained_containers + unconstrained_containers:,} containers
    
    ℹ️ **How this works:**
    - The **Constrained Allocations** table below shows containers that are locked and will NOT be changed by scenarios
    - The **Unconstrained Data** table shows containers that WILL be manipulated based on your selected scenario
    """)

    st.markdown("---")
    st.markdown("## 🔒 Constrained Allocations")
    st.markdown("**✋ These allocations are LOCKED and NOT affected by scenario selection**")

    constrained_display = constrained_data.copy()
    if 'Container Numbers' in constrained_display.columns:
        constrained_display['Container Count'] = constrained_display['Container Numbers'].apply(count_containers)

    constrained_display = add_detailed_carrier_flips_column(constrained_display, final_filtered_data, carrier_col='Dray SCAC(FL)')
    if 'Carrier Flips (Detailed)' in constrained_display.columns:
        constrained_display.rename(columns={'Carrier Flips (Detailed)': 'Carrier Flips'}, inplace=True)

    constrained_download_data = constrained_display.copy()

    # Build display columns
    cols_c = ['Discharged Port']
    for col in ['Category', 'SSL', 'Vessel']:
        if col in constrained_display.columns:
            cols_c.append(col)
    cols_c.extend([carrier_col, 'Lane', 'Facility'])
    for col in ['Terminal', 'Week Number', 'Ocean ETA', 'Container Numbers', 'Carrier Flips']:
        if col in constrained_display.columns:
            cols_c.append(col)
    cols_c.append('Container Count')
    for col in [rate_cols['rate'], rate_cols['total_rate']]:
        if col in constrained_display.columns:
            cols_c.append(col)
    for col in ['Constraint_Priority', 'Constraint_Method', 'Constraint_Description']:
        if col in constrained_display.columns:
            cols_c.append(col)

    cols_c = [c for c in cols_c if c in constrained_display.columns]
    constrained_display = constrained_display[cols_c].copy()

    rename_dict_c = {rate_cols['total_rate']: 'Total Cost'}
    if 'Constraint_Priority' in constrained_display.columns:
        rename_dict_c['Constraint_Priority'] = '🎯 Priority'
    if 'Constraint_Method' in constrained_display.columns:
        rename_dict_c['Constraint_Method'] = '📐 Method'
    if 'Constraint_Description' in constrained_display.columns:
        rename_dict_c['Constraint_Description'] = '📝 Description'
    if carrier_col == 'Dray SCAC(FL)':
        rename_dict_c['Dray SCAC(FL)'] = 'NEW SCAC'
    constrained_display = constrained_display.rename(columns=rename_dict_c)

    if rate_cols['rate'] in constrained_display.columns:
        constrained_display[rate_cols['rate']] = constrained_display[rate_cols['rate']].apply(format_currency)
    if 'Total Cost' in constrained_display.columns:
        constrained_display['Total Cost'] = constrained_display['Total Cost'].apply(format_currency)

    st.dataframe(constrained_display, use_container_width=True, hide_index=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("📊 Constrained Records", len(constrained_data))
    col2.metric("📦 Constrained Containers", f"{constrained_containers:,}")
    col3.metric("💰 Constrained Cost", f"${constrained_data[rate_cols['total_rate']].sum():,.2f}")

    st.markdown("---")
    st.markdown("---")
    st.markdown(f"## 📋 Unconstrained Data - {selected}")
    st.markdown(f"**🔄 These containers ARE manipulated by the '{selected}' scenario**")

    return constrained_download_data


def _build_columns_and_description(display_data, selected, carrier_col, rate_cols,
                                    metrics, has_constraints, constrained_data,
                                    unconstrained_data, performance_reallocated,
                                    performance_groups_impacted):
    """Pick display columns, rename, build description string. Returns (display_data, download_data, desc, filename)."""
    cols = ['Discharged Port']
    for col in ['Category', 'SSL', 'Vessel']:
        if col in display_data.columns:
            cols.append(col)
    cols.extend([carrier_col, 'Lane', 'Facility'])
    for col in ['Terminal', 'Week Number', 'Ocean ETA', 'Container Numbers', 'Carrier Flips']:
        if col in display_data.columns:
            cols.append(col)
    cols.append('Container Count')
    for col in [rate_cols['rate'], rate_cols['total_rate']]:
        if col in display_data.columns:
            cols.append(col)
    if 'Performance_Score' in display_data.columns:
        cols.append('Performance_Score')
    if 'Missing_Rate' in display_data.columns:
        cols.append('Missing_Rate')
    if 'Allocation Strategy' in display_data.columns:
        cols.append('Allocation Strategy')

    # Scenario-specific columns
    if selected == 'Optimized':
        for col in ['Carrier_Rank', 'Historical_Allocation_Pct', 'New_Allocation_Pct',
                     'Volume_Change', 'Growth_Constrained', 'Allocation_Notes']:
            if col in display_data.columns:
                cols.append(col)
    if selected == 'Performance':
        for col in ['Original Carrier Mix', 'Original Carrier Containers', 'Reallocated Containers',
                     'Original Primary Carrier', 'Original Primary Volume', 'Original Primary Performance',
                     'Carrier Change']:
            if col in display_data.columns:
                cols.append(col)

    cols = [c for c in cols if c in display_data.columns]
    download_data = display_data.copy()
    display_data = display_data[cols].copy()

    # Sort
    if selected == 'Performance' and 'Reallocated Containers' in display_data.columns:
        display_data = display_data.sort_values('Reallocated Containers', ascending=False)
    elif selected == 'Optimized' and 'Carrier_Rank' in display_data.columns:
        display_data = display_data.sort_values('Carrier_Rank', ascending=True)

    # Calculate total cost
    if selected in ('Performance', 'Optimized') and rate_cols['total_rate'] in display_data.columns:
        scenario_cost = display_data[rate_cols['total_rate']].sum()
        if has_constraints:
            c_cost = constrained_data[rate_cols['total_rate']].sum()
            total_cost = c_cost + scenario_cost
            cost_breakdown = f" (Constrained: ${c_cost:,.2f} + Unconstrained: ${scenario_cost:,.2f})"
        else:
            total_cost = scenario_cost
            cost_breakdown = ""
    else:
        if has_constraints:
            c_cost = constrained_data[rate_cols['total_rate']].sum()
            u_cost = unconstrained_data[rate_cols['total_rate']].sum()
            total_cost = c_cost + u_cost
            cost_breakdown = f" (Constrained: ${c_cost:,.2f} + Unconstrained: ${u_cost:,.2f})"
        else:
            total_cost = metrics['total_cost']
            cost_breakdown = ""

    # Rename columns
    rename_dict = {
        rate_cols['total_rate']: 'Total Cost',
        'Performance_Score': 'Performance',
        'Original Primary Performance': 'Original Lead Performance',
    }
    if carrier_col in display_data.columns:
        rename_dict[carrier_col] = 'NEW SCAC'
    if 'Missing_Rate' in display_data.columns:
        rename_dict['Missing_Rate'] = '⚠️ No Rate'
    if 'Allocation Strategy' in display_data.columns:
        rename_dict['Allocation Strategy'] = 'Strategy'
    # Performance renames
    for old, new in [('Original Carrier Containers', 'Volume Before Reallocation'),
                     ('Reallocated Containers', 'Containers Reallocated'),
                     ('Original Primary Carrier', 'Original Lead Carrier'),
                     ('Original Primary Volume', 'Original Lead Volume')]:
        if old in display_data.columns:
            rename_dict[old] = new
    # Optimized renames
    for old, new in [('Carrier_Rank', '🏅 Rank'), ('Historical_Allocation_Pct', '📊 Historical %'),
                     ('New_Allocation_Pct', '🆕 New %'), ('Volume_Change', '📈 Volume Change'),
                     ('Growth_Constrained', '🔒 Capped'), ('Allocation_Notes', '📝 Allocation Details')]:
        if old in display_data.columns:
            rename_dict[old] = new

    display_data = display_data.rename(columns=rename_dict)
    download_data = download_data.rename(columns=rename_dict)

    # Build description
    rate_type_label = st.session_state.get('rate_type', 'Base Rate')
    reallocation_note = _reallocation_note(performance_reallocated, performance_groups_impacted)

    if selected == 'Optimized':
        cost_pct = st.session_state.get('opt_cost_weight', 70)
        perf_pct = st.session_state.get('opt_performance_weight', 30)
        growth_pct = st.session_state.get('opt_max_growth_pct', 30)
        desc = (f"🧮 Optimized with LP + Historical Constraints ({rate_type_label}) - "
                f"{cost_pct}% cost, {perf_pct}% performance, max {growth_pct}% growth - "
                f"Total: ${total_cost:,.2f}{cost_breakdown}{reallocation_note}")
        filename = 'optimized_cascading.csv'
    elif selected == 'Performance':
        desc = (f"🏆 Highest performance carrier scenario ({rate_type_label}) - "
                f"Total: ${total_cost:,.2f}{cost_breakdown}{reallocation_note}")
        filename = 'performance.csv'
    else:
        desc = f"📊 Your current selections ({rate_type_label}) - Total: ${total_cost:,.2f}{cost_breakdown}"
        filename = 'current_selection.csv'

    return display_data, download_data, desc, filename


def _reallocation_note(reallocated, groups_impacted):
    if not reallocated:
        return ""
    parts = [f"{reallocated:,} containers reallocated"]
    if groups_impacted:
        label = "lane" if groups_impacted == 1 else "lanes"
        parts.append(f"across {groups_impacted} {label}")
    return " • " + " | ".join(parts)


def _format_display(display_data, rate_cols):
    """Format columns for human-readable display."""
    display_formatted = display_data.copy()
    if rate_cols['rate'] in display_formatted.columns:
        display_formatted[rate_cols['rate']] = display_formatted[rate_cols['rate']].apply(format_currency)
    if 'Total Cost' in display_formatted.columns:
        display_formatted['Total Cost'] = display_formatted['Total Cost'].apply(format_currency)
    if 'Performance' in display_formatted.columns:
        display_formatted['Performance'] = display_formatted['Performance'].apply(format_percentage)
    if 'Original Lead Performance' in display_formatted.columns:
        display_formatted['Original Lead Performance'] = display_formatted['Original Lead Performance'].apply(format_percentage)
    if 'Potential Savings' in display_formatted.columns:
        display_formatted['Potential Savings'] = display_formatted['Potential Savings'].apply(format_currency)
    if 'Savings %' in display_formatted.columns:
        display_formatted['Savings %'] = display_formatted['Savings %'].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "N/A")
    if 'Ocean ETA' in display_formatted.columns:
        display_formatted['Ocean ETA'] = pd.to_datetime(display_formatted['Ocean ETA'], errors='coerce').dt.strftime('%Y-%m-%d')
    for col in ['Container Count', 'Volume Before Reallocation', 'Original Lead Volume', 'Containers Reallocated']:
        if col in display_formatted.columns:
            display_formatted[col] = display_formatted[col].apply(
                lambda v: f"{int(n):,}" if (n := safe_numeric(v)) != 0 else "0"
            )
    return display_formatted


def _render_table_metrics(display_data, has_constraints, rate_cols):
    """Show the 3-column metrics row below the table."""
    col1, col2, col3 = st.columns(3)
    total_containers = int(round(display_data['Container Count'].sum()))
    if 'Total Cost' in display_data.columns:
        actual_cost = display_data['Total Cost'].apply(
            lambda x: float(str(x).replace('$', '').replace(',', '')) if pd.notna(x) and x != 'N/A' else 0
        ).sum()
    elif rate_cols['total_rate'] in display_data.columns:
        actual_cost = display_data[rate_cols['total_rate']].sum()
    else:
        actual_cost = 0

    label = "Unconstrained" if has_constraints else ""
    col1.metric(f"📊 {label} Records".strip(), len(display_data))
    col2.metric(f"📦 {label} Containers".strip(), f"{total_containers:,}")
    col3.metric(f"💰 {label} Cost".strip(), f"${actual_cost:,.2f}")


# ==================== SMALL DISPLAY FUNCTIONS ====================

def show_top_savings_opportunities(final_filtered_data):
    """DEPRECATED — use 'Cheapest Cost' scenario in the Detailed Analysis Table."""
    st.info("💡 Top Savings Opportunities feature has been deprecated. Use the 'Cheapest Cost' scenario in the Detailed Analysis Table to see savings opportunities.")


def show_complete_data_export(final_filtered_data):
    """Complete data export section."""
    section_header("📄 Complete Data Export")
    if len(final_filtered_data) > 0:
        csv = final_filtered_data.to_csv(index=False)
        st.download_button(label="📥 Download Complete Data", data=csv,
                           file_name='comprehensive_data.csv', mime='text/csv', use_container_width=True)


def show_performance_score_analysis(final_filtered_data):
    """Show performance score analysis and distribution."""
    if 'Performance_Score' not in final_filtered_data.columns:
        return
    section_header("📈 Performance Score Analysis")
    perf_data = final_filtered_data[final_filtered_data['Performance_Score'].notna()].copy()
    if len(perf_data) == 0:
        st.info("No performance data available for analysis.")
        return
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📊 Average Performance", f"{perf_data['Performance_Score'].mean():.1%}")
    with col2:
        st.metric("⬇️ Lowest Performance", f"{perf_data['Performance_Score'].min():.1%}")
    with col3:
        st.metric("⬆️ Highest Performance", f"{perf_data['Performance_Score'].max():.1%}")
    st.subheader("Performance by Carrier")
    carrier_perf = perf_data.groupby('Dray SCAC(FL)').agg({
        'Performance_Score': ['mean', 'min', 'max', 'count'],
        'Container Count': 'sum'
    }).round(3)
    carrier_perf.columns = ['Avg Performance', 'Min Performance', 'Max Performance', 'Records', 'Total Containers']
    carrier_perf = carrier_perf.sort_values('Avg Performance', ascending=False)
    for col in ['Avg Performance', 'Min Performance', 'Max Performance']:
        carrier_perf[col] = carrier_perf[col].apply(lambda x: f"{x:.1%}")
    st.dataframe(carrier_perf, use_container_width=True)


def show_carrier_performance_matrix(final_filtered_data):
    """Show carrier performance matrix."""
    if 'Performance_Score' not in final_filtered_data.columns:
        return
    section_header("🎯 Carrier Performance Matrix")
    perf_data = final_filtered_data[final_filtered_data['Performance_Score'].notna()].copy()
    if len(perf_data) == 0:
        st.info("No performance data available for matrix analysis.")
        return
    matrix_data = perf_data.groupby(['Dray SCAC(FL)', 'Lane']).agg({
        'Performance_Score': 'mean', 'Base Rate': 'mean'
    }).reset_index()
    perf_matrix = matrix_data.pivot(index='Dray SCAC(FL)', columns='Lane', values='Performance_Score')
    st.subheader("Performance Score Matrix (by Carrier & Lane)")
    st.dataframe(perf_matrix.applymap(lambda x: f"{x:.1%}" if pd.notna(x) else "-"), use_container_width=True)
    rate_matrix = matrix_data.pivot(index='Dray SCAC(FL)', columns='Lane', values='Base Rate')
    st.subheader("Average Rate Matrix (by Carrier & Lane)")
    st.dataframe(rate_matrix.applymap(lambda x: f"${x:,.2f}" if pd.notna(x) else "-"), use_container_width=True)


def show_container_movement_summary(current_data, baseline_data, carrier_col='Dray SCAC(FL)'):
    """Display comprehensive summary of container movements between carriers."""
    if baseline_data is None or baseline_data.empty:
        return
    if 'Container Numbers' not in baseline_data.columns:
        st.info("ℹ️ Container-level tracking not available. Upload data with 'Container Numbers' column for detailed tracing.")
        return

    section_header("🔄 Container Movement Analysis")
    summary = get_container_movement_summary(current_data, baseline_data, carrier_col)
    if 'error' in summary:
        st.warning(f"⚠️ {summary['error']}")
        return

    st.subheader("📊 Movement Overview")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Containers", f"{summary['total_containers']:,}", help="Total unique containers tracked")
    with col2:
        st.metric("✓ Kept with Original", f"{summary['total_kept']:,}", f"{summary['kept_percentage']:.1f}%",
                   help="Containers that stayed with their original carrier")
    with col3:
        st.metric("🔄 Flipped to New Carrier", f"{summary['total_flipped']:,}", f"{summary['flipped_percentage']:.1f}%",
                   help="Containers that moved to a different carrier")
    with col4:
        st.metric("🆕 Unknown/New", f"{summary['total_unknown']:,}", help="Containers not found in baseline")

    if summary['top_flows']:
        st.subheader("🔝 Top Container Flows (Carrier → Carrier)")
        flows_df = pd.DataFrame(summary['top_flows'], columns=['From Carrier', 'To Carrier', 'Container Count'])
        flows_df['% of Flipped'] = (flows_df['Container Count'] / summary['total_flipped'] * 100).round(1)
        flows_df['% of Total'] = (flows_df['Container Count'] / summary['total_containers'] * 100).round(1)
        flows_display = flows_df.copy()
        flows_display['Flow'] = flows_display.apply(lambda row: f"{row['From Carrier']} → {row['To Carrier']}", axis=1)
        flows_display['Containers'] = flows_display['Container Count'].apply(lambda x: f"{x:,}")
        flows_display['% Flipped'] = flows_display['% of Flipped'].apply(lambda x: f"{x:.1f}%")
        flows_display['% Total'] = flows_display['% of Total'].apply(lambda x: f"{x:.1f}%")
        st.dataframe(flows_display[['Flow', 'Containers', '% Flipped', '% Total']], use_container_width=True, hide_index=True)

        st.subheader("📈 Flow Visualization")
        chart_data = flows_df.head(10).copy()
        chart_data['Flow Label'] = chart_data.apply(lambda row: f"{row['From Carrier']} → {row['To Carrier']}", axis=1)
        import plotly.express as px
        fig = px.bar(chart_data, x='Container Count', y='Flow Label', orientation='h',
                     title='Top 10 Container Flows',
                     labels={'Container Count': 'Number of Containers', 'Flow Label': 'Carrier Flow'},
                     color='Container Count', color_continuous_scale='Blues')
        fig.update_layout(height=400, showlegend=False, yaxis={'categoryorder': 'total ascending'})
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("💡 Insights")
    insights = []
    if summary['kept_percentage'] > 75:
        insights.append(f"✅ **High Stability**: {summary['kept_percentage']:.1f}% of containers remained with their original carrier.")
    elif summary['kept_percentage'] < 25:
        insights.append(f"🔄 **Major Reallocation**: {summary['flipped_percentage']:.1f}% of containers were reassigned to different carriers.")
    else:
        insights.append(f"⚖️ **Balanced Changes**: {summary['kept_percentage']:.1f}% kept, {summary['flipped_percentage']:.1f}% flipped.")
    if summary['top_flows']:
        top_flow = summary['top_flows'][0]
        insights.append(f"🎯 **Largest Flow**: {top_flow[2]:,} containers moved from **{top_flow[0]}** to **{top_flow[1]}**.")
    insights.append(f"🏢 **Carrier Participation**: {summary['unique_source_carriers']} carriers lost containers, {summary['unique_destination_carriers']} carriers gained containers.")
    for insight in insights:
        st.markdown(insight)
