"""
Metrics and KPI calculation module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
import numpy as np
from .config_styling import section_header
from optimization.performance_logic import allocate_to_highest_performance

# ==================== HELPER FUNCTIONS ====================

def get_rate_columns():
    """Get the appropriate rate column names based on selected rate type"""
    rate_type = st.session_state.get('rate_type', 'Base Rate')
    
    if rate_type == 'CPC':
        return {
            'rate': 'CPC',
            'total_rate': 'Total CPC'
        }
    else:  # Base Rate (default)
        return {
            'rate': 'Base Rate',
            'total_rate': 'Total Rate'
        }

def safe_numeric(value):
    """Convert any value to float, stripping formatting if needed"""
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace('$', '').replace(',', '').replace('%', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0

def format_currency(value):
    """Format as currency"""
    return f"${value:,.2f}" if pd.notna(value) and value != 0 else "N/A"

def format_percentage(value):
    """Format as percentage"""
    return f"{value:.1%}" if pd.notna(value) else "N/A"

def get_grouping_columns(data, base_cols=['Discharged Port', 'Lane', 'Facility', 'Week Number']):
    """Get grouping columns including Category if it exists"""
    cols = base_cols.copy()
    if 'Category' in data.columns and 'Category' not in cols:
        cols.insert(1, 'Category')  # Add Category after first column
    return cols

def add_missing_rate_rows(display_data, source_data, carrier_col='Dray SCAC(FL)'):
    """Add back rows for missing rate data, preserving carrier information"""
    if 'Missing_Rate' not in source_data.columns:
        return display_data
    
    missing_rate_rows = source_data[source_data['Missing_Rate'] == True]
    if len(missing_rate_rows) == 0:
        return display_data
    
    missing_rate_rows = missing_rate_rows.copy()
    
    # Keep carrier information - include carrier in grouping columns
    group_cols = get_grouping_columns(missing_rate_rows)
    
    # Add carrier to grouping to preserve carrier-level detail
    if carrier_col in missing_rate_rows.columns and carrier_col not in group_cols:
        group_cols.append(carrier_col)
    
    # Optimize aggregation dictionary creation
    numeric_cols = missing_rate_rows.select_dtypes(include=[np.number]).columns
    agg_dict = {col: 'first' for col in missing_rate_rows.columns if col not in group_cols}
    
    # Override specific columns with custom aggregation
    agg_dict['Container Count'] = 'sum'
    agg_dict['Container Numbers'] = lambda x: ', '.join(str(v) for v in x if pd.notna(v))
    
    missing_rate_rows = missing_rate_rows.groupby(group_cols, as_index=False).agg(agg_dict)
    
    # Set rate-dependent columns to None/0 (but keep carrier as-is)
    rate_cols = ['Base Rate', 'Total Rate', 'Performance_Score', 'CPC', 'Total CPC']
    for col in rate_cols:
        if col in missing_rate_rows.columns:
            missing_rate_rows[col] = None if col in ['Base Rate', 'Performance_Score', 'CPC'] else 0
    
    return pd.concat([display_data, missing_rate_rows], ignore_index=True)

# ==================== METRICS CALCULATION ====================

def calculate_enhanced_metrics(data, unconstrained_data=None, max_constrained_carriers=None):
    """Calculate comprehensive metrics for the dashboard
    
    Args:
        data: Full dataset (may include constrained + unconstrained data)
        unconstrained_data: Optional - data excluding constrained containers.
                           When provided, scenarios (Performance, Cheapest, Optimized) 
                           will run on this subset instead of full data.
        max_constrained_carriers: Optional - set of carrier names that have Maximum Container Count constraints.
                                 These carriers should NOT receive additional volume in optimization.
    """
    if data is None or len(data) == 0:
        return None
    
    # Get rate columns based on selected rate type - cache this
    rate_cols = get_rate_columns()
    
    # Preserve a canonical total that INCLUDES rows with missing rates
    total_containers_all = data['Container Count'].sum()

    # Use ALL data regardless of rate availability
    data_with_rates = data.copy()
    
    # For scenario calculations, use unconstrained_data if provided
    # This ensures scenarios only manipulate unconstrained containers
    scenario_data = unconstrained_data.copy() if unconstrained_data is not None else data_with_rates.copy()
    
    # Store max_constrained_carriers for later use in optimization
    if max_constrained_carriers is None:
        max_constrained_carriers = set()

    # If there are no rows with rates, continue but note rate-based metrics will be zero/defaults
    
    # Basic metrics - use dynamic rate columns - vectorized operations
    # For cost calculations, only sum rows that have valid rates (not NaN)
    if rate_cols['total_rate'] in data_with_rates.columns:
        total_cost = data_with_rates[rate_cols['total_rate']].fillna(0).sum()
    else:
        total_cost = 0
    total_containers_with_rates = data_with_rates['Container Count'].sum()

    # Use vectorized operations for unique counts
    unique_carriers = data['Dray SCAC(FL)'].nunique() if 'Dray SCAC(FL)' in data.columns else 0
    unique_lanes = data['Lane'].nunique() if 'Lane' in data.columns else 0
    unique_ports = data['Discharged Port'].nunique() if 'Discharged Port' in data.columns else 0
    unique_facilities = data['Facility'].nunique() if 'Facility' in data.columns else 0

    # Average rate should be based on rows that have rates
    avg_rate = total_cost / total_containers_with_rates if total_containers_with_rates > 0 else 0
    
    # Performance averages (for reference only)
    avg_performance = data_with_rates['Performance_Score'].mean() if 'Performance_Score' in data_with_rates.columns else None

    # Calculate performance scenario cost using scenario_data (unconstrained only when constraints active)
    performance_cost = None
    if 'Performance_Score' in scenario_data.columns and len(scenario_data) > 0:
        try:
            carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in scenario_data.columns else 'Carrier'
            performance_allocated = allocate_to_highest_performance(
                scenario_data.copy(),
                carrier_column=carrier_col,
                container_column='Container Count',
                performance_column='Performance_Score',
                container_numbers_column='Container Numbers',
            )
            if rate_cols['total_rate'] in performance_allocated.columns:
                performance_cost = performance_allocated[rate_cols['total_rate']].sum()
        except (ValueError, KeyError):
            pass
    
    # Calculate cheapest cost scenario using scenario_data - optimized with early numeric conversion
    cheapest_cost = None
    if len(scenario_data) > 0:
        try:
            carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in scenario_data.columns else 'Carrier'
            
            working = scenario_data.copy()
            
            # Ensure numeric comparisons - do this once
            working[rate_cols['rate']] = pd.to_numeric(working[rate_cols['rate']], errors='coerce')
            working['Container Count'] = pd.to_numeric(working['Container Count'], errors='coerce').fillna(0)
            
            # Filter out rows with NaN/null rates
            working = working[working[rate_cols['rate']].notna()]
            
            if len(working) > 0:
                # Define grouping columns once
                group_cols_cheap = [col for col in ['Category', 'Week Number', 'Lane', 'Discharged Port', 'Facility'] 
                                   if col in working.columns]
                
                if group_cols_cheap:
                    # Sort by rate (cheapest first) - single sort operation
                    working = working.sort_values(rate_cols['rate'], ascending=True)
                    
                    # Get cheapest carrier per group
                    cheapest_per_group = working.groupby(group_cols_cheap, as_index=False).first()
                    
                    # If Container Numbers exists, concatenate them and recalculate Container Count
                    if 'Container Numbers' in working.columns:
                        # Concatenate all Container Numbers for each group
                        container_numbers_concat = (
                            working.groupby(group_cols_cheap)['Container Numbers']
                            .apply(lambda x: ', '.join(str(v) for v in x if pd.notna(v) and str(v).strip()))
                            .reset_index(name='_container_numbers_all')
                        )
                        
                        # Merge back to cheapest_per_group
                        cheapest_per_group = cheapest_per_group.merge(container_numbers_concat, on=group_cols_cheap, how='left')
                        
                        # Recalculate Container Count from concatenated Container Numbers
                        def count_containers_in_string(container_str):
                            if pd.isna(container_str) or not str(container_str).strip():
                                return 0
                            containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
                            return len(containers)
                        
                        cheapest_per_group['Container Count'] = cheapest_per_group['_container_numbers_all'].apply(count_containers_in_string)
                    else:
                        # Fall back to summing Container Count if Container Numbers doesn't exist
                        container_totals = working.groupby(group_cols_cheap)['Container Count'].sum()
                        cheapest_per_group = cheapest_per_group.set_index(group_cols_cheap)
                        cheapest_per_group['Container Count'] = container_totals
                        cheapest_per_group = cheapest_per_group.reset_index()
                    
                    # Vectorized cost calculation using the corrected Container Count
                    cheapest_per_group['Total Cost'] = (
                        cheapest_per_group[rate_cols['rate']] * cheapest_per_group['Container Count']
                    )
                    
                    cheapest_cost = cheapest_per_group['Total Cost'].sum()
        except (ValueError, KeyError):
            pass

    # Calculate optimized cost scenario using cascading logic with LP + historical constraints
    # Uses scenario_data (unconstrained only when constraints active)
    optimized_cost = None
    if len(scenario_data) > 0:
        try:
            from optimization import cascading_allocate_with_constraints
            
            carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in scenario_data.columns else 'Carrier'
            
            # Prepare optimization source - recalculate Container Count from Container Numbers
            optimization_source = scenario_data.copy()
            
            # CRITICAL: Recalculate Container Count from Container Numbers to ensure consistency
            if 'Container Numbers' in optimization_source.columns:
                def count_containers_from_string(container_str):
                    """Count actual container IDs in a comma-separated string"""
                    if pd.isna(container_str) or not str(container_str).strip():
                        return 0
                    return len([c.strip() for c in str(container_str).split(',') if c.strip()])
                
                optimization_source['Container Count'] = optimization_source['Container Numbers'].apply(count_containers_from_string)
            
            # Get optimization parameters from session state
            cost_weight = st.session_state.get('opt_cost_weight', 70) / 100.0
            performance_weight = st.session_state.get('opt_performance_weight', 30) / 100.0
            max_growth_pct = st.session_state.get('opt_max_growth_pct', 30) / 100.0
            
            optimized_allocated = cascading_allocate_with_constraints(
                optimization_source,
                max_growth_pct=max_growth_pct,
                cost_weight=cost_weight,
                performance_weight=performance_weight,
                n_historical_weeks=5,
                carrier_column=carrier_col,
                container_column='Container Count',
                excluded_carriers=max_constrained_carriers,  # Exclude carriers with maximum constraints
            )
            
            if optimized_allocated is not None and len(optimized_allocated) > 0:
                if rate_cols['total_rate'] in optimized_allocated.columns:
                    optimized_cost = optimized_allocated[rate_cols['total_rate']].sum()
        except (ValueError, KeyError, ImportError):
            pass

    return {
        'total_cost': total_cost,
        'total_containers': total_containers_all,
        'unique_carriers': unique_carriers,
        'unique_scacs': unique_carriers,  # Same as unique_carriers
        'unique_lanes': unique_lanes,
        'unique_ports': unique_ports,
        'unique_facilities': unique_facilities,
        'avg_rate': avg_rate,
        'avg_performance': avg_performance,
        'performance_cost': performance_cost,
        'cheapest_cost': cheapest_cost,
        'optimized_cost': optimized_cost
    }

# ==================== DISPLAY FUNCTIONS ====================

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
        if metrics.get('performance_cost') is not None:
            # Add constrained cost to scenario cost
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
    
    # Cheapest Cost scenario
    with col3:
        if metrics.get('cheapest_cost') is not None:
            # Add constrained cost to scenario cost
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
    
    # Optimized scenario (calculated using cascading logic with LP + historical constraints)
    with col4:
        if metrics.get('optimized_cost') is not None:
            # Add constrained cost to scenario cost
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
            st.markdown(f"""
            <div style="background-color: #e6f7ff; padding: 15px; border-radius: 10px;">
                <h4 style="color: #17a2b8; margin: 0;">🧮 Optimized</h4>
                <h2 style="color: #17a2b8; margin: 5px 0;">N/A</h2>
                <p style="margin: 0; color: #17a2b8;">Optimization unavailable<br><small>Need historical data</small></p>
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown("---")

def show_detailed_analysis_table(final_filtered_data, unconstrained_data, constrained_data, metrics=None, max_constrained_carriers=None):
    """Show detailed analysis table - uses same data source as Cost Analysis Dashboard
    
    Args:
        final_filtered_data: Complete filtered dataset
        unconstrained_data: Data not locked by constraints
        constrained_data: Data locked by constraints
        metrics: Pre-calculated metrics (optional)
        max_constrained_carriers: Set of carriers with maximum constraints (optional)
    """
    section_header("📋 Detailed Analysis Table")
    
    # Default to empty set if not provided
    if max_constrained_carriers is None:
        max_constrained_carriers = set()
    
    bal_wk47_final = final_filtered_data[
        (final_filtered_data['Discharged Port'] == 'BAL') & 
        (final_filtered_data['Week Number'] == 47)
    ]
    bal_wk47_uncon = unconstrained_data[
        (unconstrained_data['Discharged Port'] == 'BAL') & 
        (unconstrained_data['Week Number'] == 47)
    ] if len(unconstrained_data) > 0 else pd.DataFrame()
    bal_wk47_con = constrained_data[
        (constrained_data['Discharged Port'] == 'BAL') & 
        (constrained_data['Week Number'] == 47)
    ] if len(constrained_data) > 0 else pd.DataFrame()
    
    # Get metrics if not provided
    if metrics is None:
        metrics = calculate_enhanced_metrics(final_filtered_data)
    
    if metrics is None:
        st.warning("⚠️ No data available for analysis.")
        return
    
    # Check if constraints are active
    has_constraints = len(constrained_data) > 0 if isinstance(constrained_data, pd.DataFrame) else False
    
    # Show constraint status
    if not has_constraints:
        st.info("ℹ️ **No constraints active** - All containers in the table below can be manipulated by scenarios")
    
    # Strategy selector
    strategy_options = ['Current Selection', 'Performance', 'Cheapest Cost', 'Optimized']
    
    selected = st.selectbox("📊 Select Strategy:", strategy_options)
    
    # Show constraint info if applicable
    if has_constraints:
        # Recalculate constrained container count from Container Numbers for accuracy
        if 'Container Numbers' in constrained_data.columns:
            def count_containers_from_string(container_str):
                """Count actual container IDs in a comma-separated string"""
                if pd.isna(container_str) or not str(container_str).strip():
                    return 0
                return len([c.strip() for c in str(container_str).split(',') if c.strip()])
            
            constrained_containers = constrained_data['Container Numbers'].apply(count_containers_from_string).sum()
        else:
            constrained_containers = constrained_data['Container Count'].sum()
        
        # Recalculate unconstrained container count from Container Numbers for accuracy
        if 'Container Numbers' in unconstrained_data.columns:
            def count_containers_from_string(container_str):
                """Count actual container IDs in a comma-separated string"""
                if pd.isna(container_str) or not str(container_str).strip():
                    return 0
                return len([c.strip() for c in str(container_str).split(',') if c.strip()])
            
            unconstrained_containers = unconstrained_data['Container Numbers'].apply(count_containers_from_string).sum()
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
        
        # Show constrained data section for ALL scenarios
        st.markdown("---")
        st.markdown("## 🔒 Constrained Allocations")
        st.markdown("**✋ These allocations are LOCKED and NOT affected by scenario selection**")
        
        # Get dynamic rate columns
        rate_cols = get_rate_columns()
        
        constrained_display = constrained_data.copy()
        
        # CRITICAL: Recalculate Container Count from Container Numbers to ensure accuracy
        # This ensures container counts match the actual concatenated container IDs
        if 'Container Numbers' in constrained_display.columns:
            def count_containers_from_string(container_str):
                """Count actual container IDs in a comma-separated string"""
                if pd.isna(container_str) or not str(container_str).strip():
                    return 0
                return len([c.strip() for c in str(container_str).split(',') if c.strip()])
            
            constrained_display['Container Count'] = constrained_display['Container Numbers'].apply(count_containers_from_string)
        
        # Prepare constrained data for display
        carrier_col_c = 'Carrier' if 'Carrier' in constrained_display.columns else 'Dray SCAC(FL)'
        cols_c = ['Discharged Port']
        if 'Category' in constrained_display.columns:
            cols_c.append('Category')
        cols_c.extend([carrier_col_c, 'Lane', 'Facility', 'Week Number'])
        if 'Container Numbers' in constrained_display.columns:
            cols_c.append('Container Numbers')
        
        # Add selected rate columns
        cols_c.append('Container Count')
        if rate_cols['rate'] in constrained_display.columns:
            cols_c.append(rate_cols['rate'])
        if rate_cols['total_rate'] in constrained_display.columns:
            cols_c.append(rate_cols['total_rate'])
        
        # Add constraint columns if they exist
        if 'Constraint_Priority' in constrained_display.columns:
            cols_c.append('Constraint_Priority')
        if 'Constraint_Method' in constrained_display.columns:
            cols_c.append('Constraint_Method')
        if 'Constraint_Description' in constrained_display.columns:
            cols_c.append('Constraint_Description')
        
        cols_c = [c for c in cols_c if c in constrained_display.columns]
        constrained_display = constrained_display[cols_c].copy()
        
        # Rename columns
        rename_dict_c = {
            rate_cols['total_rate']: 'Total Cost'
        }
        
        if 'Constraint_Priority' in constrained_display.columns:
            rename_dict_c['Constraint_Priority'] = '🎯 Priority'
        if 'Constraint_Method' in constrained_display.columns:
            rename_dict_c['Constraint_Method'] = '📐 Method'
        if 'Constraint_Description' in constrained_display.columns:
            rename_dict_c['Constraint_Description'] = '📝 Description'
        
        if carrier_col_c == 'Dray SCAC(FL)':
            rename_dict_c['Dray SCAC(FL)'] = 'Carrier'
        constrained_display = constrained_display.rename(columns=rename_dict_c)
        
        # Format constrained data
        if rate_cols['rate'] in constrained_display.columns:
            constrained_display[rate_cols['rate']] = constrained_display[rate_cols['rate']].apply(format_currency)
        if 'Total Cost' in constrained_display.columns:
            constrained_display['Total Cost'] = constrained_display['Total Cost'].apply(format_currency)
        
        st.dataframe(constrained_display, use_container_width=True, hide_index=True)
        
        # Constrained data metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("📊 Constrained Records", len(constrained_data))
        col2.metric("📦 Constrained Containers", f"{constrained_containers:,}")
        col3.metric("💰 Constrained Cost", f"${constrained_data[rate_cols['total_rate']].sum():,.2f}")
        
        st.markdown("---")
        st.markdown("---")
        st.markdown(f"## 📋 Unconstrained Data - {selected}")
        st.markdown(f"**🔄 These containers ARE manipulated by the '{selected}' scenario**")
    
    # Use unconstrained data for scenarios when constraints are active
    display_data = unconstrained_data.copy() if has_constraints else final_filtered_data.copy()
    
    bal_wk47_scenario_source = display_data[
        (display_data['Discharged Port'] == 'BAL') & 
        (display_data['Week Number'] == 47)
    ]
    
    # Use ALL data regardless of rate availability - no filtering
    display_data_with_rates = display_data.copy()
    missing_rate_rows = pd.DataFrame()  # Empty dataframe - not needed anymore
    
    # Select and rename columns based on strategy
    if selected in ('Current Selection', 'Performance', 'Optimized'):
        # Get dynamic rate columns based on selection
        rate_cols = get_rate_columns()

        # Always prefer 'Dray SCAC(FL)' as it's the source column from GVT data
        carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in display_data_with_rates.columns else 'Carrier'

        performance_reallocated = 0
        performance_groups_impacted = 0
        
        # For Current Selection, use the filtered data directly
        if selected == 'Current Selection':
            display_data = display_data_with_rates.copy()
            
            # CRITICAL: Recalculate Container Count from Container Numbers to ensure accuracy
            # This ensures container counts match the actual concatenated container IDs after grouping
            if 'Container Numbers' in display_data.columns:
                def count_containers_from_string(container_str):
                    """Count actual container IDs in a comma-separated string"""
                    if pd.isna(container_str) or not str(container_str).strip():
                        return 0
                    return len([c.strip() for c in str(container_str).split(',') if c.strip()])
                
                display_data['Container Count'] = display_data['Container Numbers'].apply(count_containers_from_string)
        
        # When viewing the optimized scenario, reallocate volume using cascading logic with LP + historical constraints
        elif selected == 'Optimized':
            from optimization import cascading_allocate_with_constraints
            
            # Use data_with_rates to ensure consistent container counts across all scenarios
            optimization_source = display_data_with_rates.copy()
            
            # Recalculate Container Count from Container Numbers to fix input data mismatches
            if 'Container Numbers' in optimization_source.columns:
                def count_containers_from_string(container_str):
                    """Count actual container IDs in a comma-separated string"""
                    if pd.isna(container_str) or not str(container_str).strip():
                        return 0
                    return len([c.strip() for c in str(container_str).split(',') if c.strip()])
                
                optimization_source['Container Count'] = optimization_source['Container Numbers'].apply(count_containers_from_string)
            
            # Get optimization parameters from session state (set by sliders in Optimization Settings tab)
            cost_weight = st.session_state.get('opt_cost_weight', 70) / 100.0  # Convert from % to decimal
            performance_weight = st.session_state.get('opt_performance_weight', 30) / 100.0
            max_growth_pct = st.session_state.get('opt_max_growth_pct', 30) / 100.0
            
            try:
                allocated = cascading_allocate_with_constraints(
                    optimization_source,
                    max_growth_pct=max_growth_pct,
                    cost_weight=cost_weight,
                    performance_weight=performance_weight,
                    n_historical_weeks=5,   # Last 5 weeks of data
                    carrier_column=carrier_col,
                    container_column='Container Count',
                    excluded_carriers=max_constrained_carriers,  # Exclude carriers with maximum constraints
                )
            except (ValueError, ImportError) as exc:
                st.warning(f"Unable to build optimized scenario: {exc}")
                display_data = optimization_source
            else:
                display_data = allocated
                
                # Calculate how many containers were reallocated/impacted
                if 'Volume_Change' in display_data.columns:
                    # Convert to numeric first in case it's a string
                    volume_change_numeric = pd.to_numeric(display_data['Volume_Change'], errors='coerce').fillna(0)
                    optimized_reallocated = int(abs(volume_change_numeric).sum() / 2)  # Divide by 2 to avoid double counting
                    performance_reallocated = optimized_reallocated  # Reuse variable for display logic
                    
                    group_cols = [
                        col for col in ['Discharged Port', 'Category', 'Lane', 'Facility', 'Week Number']
                        if col in display_data.columns
                    ]
                    if group_cols and optimized_reallocated > 0:
                        performance_groups_impacted = int(
                            display_data.loc[
                                volume_change_numeric != 0,
                                group_cols
                            ]
                            .drop_duplicates()
                            .shape[0]
                        )

        # When viewing the performance scenario, reallocate volume using performance_logic
        elif selected == 'Performance':
            # Use data_with_rates to ensure consistent container counts across all scenarios
            performance_source = display_data_with_rates.copy()
            
            # Recalculate Container Count from Container Numbers to fix input data mismatches
            if 'Container Numbers' in performance_source.columns:
                def count_containers_from_string(container_str):
                    """Count actual container IDs in a comma-separated string"""
                    if pd.isna(container_str) or not str(container_str).strip():
                        return 0
                    return len([c.strip() for c in str(container_str).split(',') if c.strip()])
                
                performance_source['Container Count'] = performance_source['Container Numbers'].apply(count_containers_from_string)
            
            if carrier_col in performance_source.columns:
                performance_source['Original Carrier'] = performance_source[carrier_col]
            try:
                allocated = allocate_to_highest_performance(
                    performance_source,
                    carrier_column=carrier_col,
                    container_column='Container Count',
                    performance_column='Performance_Score',
                    container_numbers_column='Container Numbers',
                )
            except ValueError as exc:
                st.warning(f"Unable to build performance scenario: {exc}")
                display_data = performance_source
            else:
                group_cols = [
                    col for col in ['Discharged Port', 'Category', 'Lane', 'Facility', 'Week Number']
                    if col in performance_source.columns
                ]

                if not group_cols:
                    group_cols = [col for col in ['Week Number'] if col in performance_source.columns]

                # Build reference information so the table shows how volume changed
                original_mix = (
                    performance_source.groupby(group_cols)[carrier_col]
                    .apply(lambda carriers: ', '.join(sorted({str(v) for v in carriers if pd.notna(v)})))
                    .reset_index(name='Original Carrier Mix')
                ) if group_cols else pd.DataFrame(columns=['Original Carrier Mix'])

                original_carrier_totals = (
                    performance_source.groupby(group_cols + [carrier_col])['Container Count']
                    .sum()
                    .reset_index(name='Original Carrier Containers')
                ) if group_cols else pd.DataFrame(columns=['Original Carrier Containers'])

                original_primary = (
                    performance_source.sort_values(
                        ['Container Count', 'Performance_Score'], ascending=[False, False]
                    )
                    .groupby(group_cols, as_index=False)
                    .first()
                ) if group_cols else pd.DataFrame()

                display_data = allocated.merge(original_mix, on=group_cols, how='left') if not original_mix.empty else allocated
                if not original_carrier_totals.empty:
                    display_data = display_data.merge(
                        original_carrier_totals,
                        on=group_cols + [carrier_col],
                        how='left'
                    )
                    display_data['Original Carrier Containers'] = (
                        display_data['Original Carrier Containers'].fillna(0)
                    )
                    display_data['Reallocated Containers'] = (
                        display_data['Container Count'] - display_data['Original Carrier Containers']
                    )
                else:
                    display_data['Original Carrier Containers'] = 0
                    display_data['Reallocated Containers'] = display_data['Container Count']

                if not original_primary.empty:
                    primary_cols = [col for col in group_cols]
                    for col in ['Original Carrier', 'Container Count', 'Performance_Score']:
                        if col in original_primary.columns:
                            primary_cols.append(col)
                    original_primary = original_primary[primary_cols].rename(
                        columns={
                            'Original Carrier': 'Original Primary Carrier',
                            'Container Count': 'Original Primary Volume',
                            'Performance_Score': 'Original Primary Performance',
                        }
                    )
                    display_data = display_data.merge(original_primary, on=group_cols, how='left')

                if 'Original Carrier Containers' in display_data.columns:
                    display_data['Original Carrier Containers'] = (
                        display_data['Original Carrier Containers'].round(0).astype(int)
                    )
                if 'Reallocated Containers' in display_data.columns:
                    display_data['Reallocated Containers'] = (
                        display_data['Reallocated Containers'].round(0).astype(int)
                    )
                    performance_reallocated = int(display_data['Reallocated Containers'].sum())
                    if group_cols:
                        performance_groups_impacted = int(
                            display_data.loc[
                                display_data['Reallocated Containers'] > 0,
                                group_cols
                            ]
                            .drop_duplicates()
                            .shape[0]
                        )
                    elif performance_reallocated:
                        performance_groups_impacted = 1

                if (
                    'Original Primary Carrier' in display_data.columns
                    and carrier_col in display_data.columns
                ):
                    display_data['Carrier Change'] = display_data[carrier_col].astype(str) + ' ← ' + display_data['Original Primary Carrier'].fillna('N/A').astype(str)

        cols = ['Discharged Port']
        if 'Category' in display_data.columns:
            cols.append('Category')
        cols.extend([carrier_col, 'Lane', 'Facility', 'Week Number'])
        if 'Container Numbers' in display_data.columns:
            cols.append('Container Numbers')

        # Add container count and selected rate columns
        cols.append('Container Count')
        if rate_cols['rate'] in display_data.columns:
            cols.append(rate_cols['rate'])
        if rate_cols['total_rate'] in display_data.columns:
            cols.append(rate_cols['total_rate'])

        # Add Performance Score
        if 'Performance_Score' in display_data.columns:
            cols.append('Performance_Score')

        # Add Missing_Rate indicator if it exists
        if 'Missing_Rate' in display_data.columns:
            cols.append('Missing_Rate')

        if 'Allocation Strategy' in display_data.columns:
            cols.append('Allocation Strategy')

        # Add columns specific to Optimized scenario (cascading logic)
        if selected == 'Optimized':
            if 'Carrier_Rank' in display_data.columns:
                cols.append('Carrier_Rank')
            if 'Historical_Allocation_Pct' in display_data.columns:
                cols.append('Historical_Allocation_Pct')
            if 'New_Allocation_Pct' in display_data.columns:
                cols.append('New_Allocation_Pct')
            if 'Volume_Change' in display_data.columns:
                cols.append('Volume_Change')
            if 'Growth_Constrained' in display_data.columns:
                cols.append('Growth_Constrained')
            if 'Allocation_Notes' in display_data.columns:
                cols.append('Allocation_Notes')

        # Add columns specific to Performance scenario
        if selected == 'Performance':
            if 'Original Carrier Mix' in display_data.columns:
                cols.append('Original Carrier Mix')
            if 'Original Carrier Containers' in display_data.columns:
                cols.append('Original Carrier Containers')
            if 'Reallocated Containers' in display_data.columns:
                cols.append('Reallocated Containers')
            if 'Original Primary Carrier' in display_data.columns:
                cols.append('Original Primary Carrier')
            if 'Original Primary Volume' in display_data.columns:
                cols.append('Original Primary Volume')
            if 'Original Primary Performance' in display_data.columns:
                cols.append('Original Primary Performance')
            if 'Carrier Change' in display_data.columns:
                cols.append('Carrier Change')

        # Select only existing columns
        cols = [c for c in cols if c in display_data.columns]
        display_data = display_data[cols].copy()

        # Sort data based on scenario
        if selected == 'Performance' and 'Reallocated Containers' in display_data.columns:
            display_data = display_data.sort_values('Reallocated Containers', ascending=False)
        elif selected == 'Optimized' and 'Carrier_Rank' in display_data.columns:
            # Sort by carrier rank (best first) within each group
            display_data = display_data.sort_values('Carrier_Rank', ascending=True)

        # Calculate total cost before renaming for scenarios that adjust allocations
        if selected in ('Performance', 'Optimized') and rate_cols['total_rate'] in display_data.columns:
            scenario_cost = display_data[rate_cols['total_rate']].sum()
            if has_constraints:
                constrained_cost = constrained_data[rate_cols['total_rate']].sum()
                total_cost = constrained_cost + scenario_cost
                cost_breakdown = f" (Constrained: ${constrained_cost:,.2f} + Unconstrained: ${scenario_cost:,.2f})"
            else:
                total_cost = scenario_cost
                cost_breakdown = ""
        else:
            # Use metrics for current cost
            if has_constraints:
                constrained_cost = constrained_data[rate_cols['total_rate']].sum()
                unconstrained_cost = unconstrained_data[rate_cols['total_rate']].sum()
                total_cost = constrained_cost + unconstrained_cost
                cost_breakdown = f" (Constrained: ${constrained_cost:,.2f} + Unconstrained: ${unconstrained_cost:,.2f})"
            else:
                total_cost = metrics['total_cost']
                cost_breakdown = ""

        # Rename columns dynamically based on rate type
        rename_dict = {
            rate_cols['total_rate']: 'Total Cost',
            'Performance_Score': 'Performance',
            'Original Primary Performance': 'Original Lead Performance'
        }
        # Always rename carrier column to 'Carrier' for consistency
        if carrier_col in display_data.columns:
            rename_dict[carrier_col] = 'Carrier'
        if 'Missing_Rate' in display_data.columns:
            rename_dict['Missing_Rate'] = '⚠️ No Rate'
        if 'Allocation Strategy' in display_data.columns:
            rename_dict['Allocation Strategy'] = 'Strategy'
        
        # Performance scenario renames
        if 'Original Carrier Containers' in display_data.columns:
            rename_dict['Original Carrier Containers'] = 'Volume Before Reallocation'
        if 'Reallocated Containers' in display_data.columns:
            rename_dict['Reallocated Containers'] = 'Containers Reallocated'
        if 'Original Primary Carrier' in display_data.columns:
            rename_dict['Original Primary Carrier'] = 'Original Lead Carrier'
        if 'Original Primary Volume' in display_data.columns:
            rename_dict['Original Primary Volume'] = 'Original Lead Volume'
        
        # Optimized (cascading) scenario renames
        if 'Carrier_Rank' in display_data.columns:
            rename_dict['Carrier_Rank'] = '🏅 Rank'
        if 'Historical_Allocation_Pct' in display_data.columns:
            rename_dict['Historical_Allocation_Pct'] = '📊 Historical %'
        if 'New_Allocation_Pct' in display_data.columns:
            rename_dict['New_Allocation_Pct'] = '🆕 New %'
        if 'Volume_Change' in display_data.columns:
            rename_dict['Volume_Change'] = '📈 Volume Change'
        if 'Growth_Constrained' in display_data.columns:
            rename_dict['Growth_Constrained'] = '🔒 Capped'
        if 'Allocation_Notes' in display_data.columns:
            rename_dict['Allocation_Notes'] = '📝 Allocation Details'
            
        display_data = display_data.rename(columns=rename_dict)
        
        # No need to add back missing rate rows since we're keeping all data now

        # Get rate type label for description
        rate_type_label = st.session_state.get('rate_type', 'Base Rate')
        if selected == 'Optimized':
            # Get current slider settings
            cost_pct = st.session_state.get('opt_cost_weight', 70)
            perf_pct = st.session_state.get('opt_performance_weight', 30)
            growth_pct = st.session_state.get('opt_max_growth_pct', 30)
            
            reallocation_note = ""
            if performance_reallocated:
                change_note_parts = [f"{performance_reallocated:,} containers reallocated"]
                if performance_groups_impacted:
                    lane_label = "lane" if performance_groups_impacted == 1 else "lanes"
                    change_note_parts.append(f"across {performance_groups_impacted} {lane_label}")
                reallocation_note = " • " + " | ".join(change_note_parts)
            desc = (
                f"🧮 Optimized with LP + Historical Constraints ({rate_type_label}) - "
                f"{cost_pct}% cost, {perf_pct}% performance, max {growth_pct}% growth - Total: ${total_cost:,.2f}{cost_breakdown}{reallocation_note}"
            )
            filename = 'optimized_cascading.csv'
        elif selected == 'Performance':
            reallocation_note = ""
            if performance_reallocated:
                change_note_parts = [f"{performance_reallocated:,} containers reallocated"]
                if performance_groups_impacted:
                    lane_label = "lane" if performance_groups_impacted == 1 else "lanes"
                    change_note_parts.append(f"across {performance_groups_impacted} {lane_label}")
                reallocation_note = " • " + " | ".join(change_note_parts)
            desc = (
                f"🏆 Highest performance carrier scenario ({rate_type_label}) - Total: ${total_cost:,.2f}{cost_breakdown}{reallocation_note}"
            )
            filename = 'performance.csv'
        else:
            desc = f"📊 Your current selections ({rate_type_label}) - Total: ${total_cost:,.2f}{cost_breakdown}"
            filename = 'current_selection.csv'
        
    elif selected == 'Cheapest Cost':
        # Get dynamic rate columns
        rate_cols = get_rate_columns()
        
        # Use unconstrained data when constraints are active
        source_data = unconstrained_data.copy() if has_constraints else final_filtered_data.copy()
        
        # Recalculate Container Count from Container Numbers to fix input data mismatches
        if 'Container Numbers' in source_data.columns:
            def count_containers_from_string(container_str):
                """Count actual container IDs in a comma-separated string"""
                if pd.isna(container_str) or not str(container_str).strip():
                    return 0
                return len([c.strip() for c in str(container_str).split(',') if c.strip()])
            
            source_data['Container Count'] = source_data['Container Numbers'].apply(count_containers_from_string)
        
        # Keep ALL carriers regardless of rate availability
        # Ensure rate column is numeric but don't filter out NaN values yet
        if rate_cols['rate'] in source_data.columns:
            source_data[rate_cols['rate']] = pd.to_numeric(source_data[rate_cols['rate']], errors='coerce')
        
        if len(source_data) == 0:
            st.warning("⚠️ No carriers with valid rates found for cheapest cost analysis.")
            display_data = pd.DataFrame()
        else:
            # Group by Category, Week Number, and Lane
            # Then aggregate containers and find the cheapest carrier per group
            carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in source_data.columns else 'Carrier'
            
            # Define grouping columns
            group_cols = []
            if 'Category' in source_data.columns:
                group_cols.append('Category')
            if 'Week Number' in source_data.columns:
                group_cols.append('Week Number')
            if 'Lane' in source_data.columns:
                group_cols.append('Lane')
            
            # Add other relevant grouping columns
            for col in ['Discharged Port', 'Facility']:
                if col in source_data.columns and col not in group_cols:
                    group_cols.append(col)
            
            if not group_cols:
                st.warning("⚠️ No grouping columns (Category, Week Number, Lane) found in data.")
                display_data = source_data.copy()
            else:
                # For each group, find the carrier with the minimum rate
                # First, sort by rate to ensure we get the cheapest carrier
                working = source_data.copy()
                
                # Ensure numeric comparisons
                working['Container Count'] = pd.to_numeric(working['Container Count'], errors='coerce').fillna(0)
                
                # Sort by rate (cheapest first) and carrier name for tie-breaking
                working['_rate_sort'] = working[rate_cols['rate']].fillna(float('inf'))
                working['_carrier_sort'] = working[carrier_col].astype(str)
                working = working.sort_values(['_rate_sort', '_carrier_sort'], ascending=[True, True])
                
                # Get the first (cheapest) carrier for each group
                cheapest_per_group = working.groupby(group_cols, as_index=False).first()
            
            # Sum all containers in each group
            container_totals = (
                working.groupby(group_cols, as_index=False)['Container Count']
                .sum()
                .rename(columns={'Container Count': '_total_containers'})
            )
            
            # Concatenate all container numbers in each group
            # Concatenate all container numbers if present
            if 'Container Numbers' in working.columns:
                container_numbers = (
                    working.groupby(group_cols)['Container Numbers']
                    .apply(lambda x: ', '.join(str(v) for v in x if pd.notna(v) and str(v).strip()))
                    .reset_index(name='_container_numbers')
                )
                cheapest_per_group = cheapest_per_group.merge(container_numbers, on=group_cols, how='left')
                cheapest_per_group['Container Numbers'] = cheapest_per_group['_container_numbers'].fillna('')
                
                # Recalculate Container Count based on actual container IDs in the concatenated string
                # This ensures Container Count matches the number of containers listed in Container Numbers
                def count_containers_in_string(container_str):
                    """Count actual container IDs in a comma-separated string"""
                    if pd.isna(container_str) or not str(container_str).strip():
                        return 0
                    # Split by comma and count non-empty items
                    containers = [c.strip() for c in str(container_str).split(',') if c.strip()]
                    return len(containers)
                
                cheapest_per_group['_actual_container_count'] = cheapest_per_group['Container Numbers'].apply(count_containers_in_string)
            
            # Assign total containers to the cheapest carrier
            cheapest_per_group = cheapest_per_group.merge(container_totals, on=group_cols, how='left')
            
            # Use the actual count from Container Numbers if available, otherwise use the sum
            if 'Container Numbers' in working.columns and '_actual_container_count' in cheapest_per_group.columns:
                # Use the corrected count
                cheapest_per_group['Container Count'] = cheapest_per_group['_actual_container_count']
            else:
                cheapest_per_group['Container Count'] = cheapest_per_group['_total_containers'].fillna(0)
            
            # Calculate total cost using the cheapest carrier's rate
            cheapest_per_group['Total Cost'] = (
                cheapest_per_group[rate_cols['rate']].fillna(0) * 
                cheapest_per_group['Container Count']
            )
            
            # Calculate current total cost for comparison
            current_cost_per_group = working.groupby(group_cols)[rate_cols['total_rate']].sum().reset_index()
            current_cost_per_group = current_cost_per_group.rename(columns={rate_cols['total_rate']: '_current_total_cost'})
            cheapest_per_group = cheapest_per_group.merge(current_cost_per_group, on=group_cols, how='left')
            
            # Calculate potential savings
            cheapest_per_group['Potential Savings'] = (
                cheapest_per_group['_current_total_cost'].fillna(0) - 
                cheapest_per_group['Total Cost']
            )
            cheapest_per_group['Savings Percentage'] = cheapest_per_group.apply(
                lambda row: (
                    row['Potential Savings'] / row['_current_total_cost'] * 100
                ) if row['_current_total_cost'] > 0 else 0,
                axis=1
            )
            
            # Clean up helper columns
            for col in ['_rate_sort', '_carrier_sort', '_total_containers', '_container_numbers', '_current_total_cost', '_actual_container_count', '_summed_count']:
                if col in cheapest_per_group.columns:
                    cheapest_per_group = cheapest_per_group.drop(columns=col)
            
            display_data = cheapest_per_group
        
        # Select and rename columns for display
        cols = group_cols.copy()
        cols.insert(0, carrier_col)
        if 'Container Numbers' in display_data.columns:
            cols.append('Container Numbers')
        cols.extend(['Container Count', rate_cols['rate'], 'Total Cost', 'Potential Savings', 'Savings Percentage'])
        
        # Add Missing_Rate indicator if it exists
        if 'Missing_Rate' in display_data.columns:
            cols.append('Missing_Rate')
        
        display_data = display_data[[c for c in cols if c in display_data.columns]].copy()
        display_data = display_data.rename(columns={
            'Savings Percentage': 'Savings %',
            carrier_col: 'Carrier',
            'Missing_Rate': '⚠️ No Rate'
        }).sort_values('Potential Savings', ascending=False)
        
        # Calculate total cost from the display data
        cheapest_cost = display_data['Total Cost'].sum() if 'Total Cost' in display_data.columns else 0
        if has_constraints:
            constrained_cost = constrained_data[rate_cols['total_rate']].sum()
            total_cost = constrained_cost + cheapest_cost
            cost_breakdown = f" (Constrained: ${constrained_cost:,.2f} + Unconstrained: ${cheapest_cost:,.2f})"
        else:
            total_cost = cheapest_cost
            cost_breakdown = ""
        
        rate_type_label = st.session_state.get('rate_type', 'Base Rate')
        desc = f"💰 Cheapest carrier per lane/week/category ({rate_type_label}) - Total: ${total_cost:,.2f}{cost_breakdown}"
        filename = 'cheapest_cost.csv'
        
        # ADD BACK MISSING RATE ROWS for Cheapest Cost scenario to maintain consistent container counts
        if len(missing_rate_rows) > 0:
            display_data = pd.concat([display_data, missing_rate_rows], ignore_index=True)
        
    st.info(desc)
    
    bal_wk47_final_display = display_data[
        (display_data['Discharged Port'] == 'BAL') & 
        (display_data['Week Number'] == 47)
    ] if 'Discharged Port' in display_data.columns else pd.DataFrame()
    # Format columns for display - use dynamic rate columns
    rate_cols = get_rate_columns()
    display_formatted = display_data.copy()
    
    # Format the active rate column (either Base Rate or CPC)
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
    for col in ['Container Count', 'Volume Before Reallocation', 'Original Lead Volume', 'Containers Reallocated']:
        if col in display_formatted.columns:
            display_formatted[col] = display_formatted[col].apply(
                lambda v: f"{int(n):,}" if (n := safe_numeric(v)) != 0 else "0"
            )
    
    # Show table
    st.dataframe(display_formatted, use_container_width=True, hide_index=True)
    
    # Metrics (use correct container counts from displayed data)
    col1, col2, col3 = st.columns(3)
    
    # Always show container count from display_data to match what's shown in the table
    # Round to integer to avoid decimal display
    total_displayed_containers = int(round(display_data['Container Count'].sum()))
    
    # Calculate actual cost from the displayed data (includes both optimized/modified rows AND missing-rate rows)
    rate_cols = get_rate_columns()
    if 'Total Cost' in display_data.columns:
        # Already renamed - convert back to calculate
        actual_displayed_cost = display_data['Total Cost'].apply(lambda x: float(str(x).replace('$', '').replace(',', '')) if pd.notna(x) and x != 'N/A' else 0).sum()
    elif rate_cols['total_rate'] in display_data.columns:
        actual_displayed_cost = display_data[rate_cols['total_rate']].sum()
    else:
        actual_displayed_cost = 0
    
    if has_constraints:
        col1.metric("📊 Unconstrained Records", len(display_data))
        col2.metric("📦 Unconstrained Containers", f"{total_displayed_containers:,}")
        col3.metric("💰 Unconstrained Cost", f"${actual_displayed_cost:,.2f}")
    else:
        col1.metric("📊 Records", len(display_data))
        col2.metric("📦 Total Containers", f"{total_displayed_containers:,}")
        col3.metric("💰 Total Cost", f"${actual_displayed_cost:,.2f}")
    
    # Download
    csv = display_data.to_csv(index=False)
    label_suffix = " (Unconstrained)" if has_constraints else ""
    st.download_button(
        label=f"📥 Download {selected}{label_suffix}",
        data=csv,
        file_name=filename,
        mime='text/csv',
        use_container_width=True
    )
    
    # Option to download constrained data separately
    if has_constraints:
        constrained_csv = constrained_data.to_csv(index=False)
        st.download_button(
            label=f"📥 Download Constrained Allocations",
            data=constrained_csv,
            file_name='constrained_allocations.csv',
            mime='text/csv',
            use_container_width=True,
            key='download_constrained'
        )

def show_top_savings_opportunities(final_filtered_data):
    """Show top 10 savings opportunities - DEPRECATED
    
    This function has been deprecated as it relied on pre-calculated 
    'Cheapest Base Rate' and 'Potential Savings' columns that are 
    no longer generated in the data processing pipeline.
    """
    st.info("💡 Top Savings Opportunities feature has been deprecated. Use the 'Cheapest Cost' scenario in the Detailed Analysis Table to see savings opportunities.")

def show_complete_data_export(final_filtered_data):
    """Complete data export section"""
    section_header("📄 Complete Data Export")
    
    if len(final_filtered_data) > 0:
        csv = final_filtered_data.to_csv(index=False)
        st.download_button(
            label="📥 Download Complete Data",
            data=csv,
            file_name='comprehensive_data.csv',
            mime='text/csv',
            use_container_width=True
        )

def show_performance_score_analysis(final_filtered_data):
    """Show performance score analysis and distribution"""
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
    """Show carrier performance matrix"""
    if 'Performance_Score' not in final_filtered_data.columns:
        return
    
    section_header("🎯 Carrier Performance Matrix")
    
    perf_data = final_filtered_data[final_filtered_data['Performance_Score'].notna()].copy()
    
    if len(perf_data) == 0:
        st.info("No performance data available for matrix analysis.")
        return
    
    matrix_data = perf_data.groupby(['Dray SCAC(FL)', 'Lane']).agg({
        'Performance_Score': 'mean',
        'Base Rate': 'mean'
    }).reset_index()
    
    perf_matrix = matrix_data.pivot(index='Dray SCAC(FL)', columns='Lane', values='Performance_Score')
    
    st.subheader("Performance Score Matrix (by Carrier & Lane)")
    st.dataframe(perf_matrix.applymap(lambda x: f"{x:.1%}" if pd.notna(x) else "-"), use_container_width=True)
    
    rate_matrix = matrix_data.pivot(index='Dray SCAC(FL)', columns='Lane', values='Base Rate')
    
    st.subheader("Average Rate Matrix (by Carrier & Lane)")
    st.dataframe(rate_matrix.applymap(lambda x: f"${x:,.2f}" if pd.notna(x) else "-"), use_container_width=True)
