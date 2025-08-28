"""
Metrics and KPI calculation module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header
from .performance_calculator import calculate_performance_optimization
from .optimization import get_optimization_results

def calculate_enhanced_metrics(final_filtered_data):
    """Calculate enhanced metrics including alternative optimization strategies"""
    if len(final_filtered_data) == 0:
        return None
        
    # Basic metrics
    total_cost = final_filtered_data['Total Rate'].sum()
    cheapest_total_cost = final_filtered_data['Cheapest Total Rate'].sum()
    total_potential_savings = final_filtered_data['Potential Savings'].sum()
    avg_rate = final_filtered_data['Base Rate'].mean()
    avg_cheapest_rate = final_filtered_data['Cheapest Base Rate'].mean()
    
    metrics = {
        'total_cost': total_cost,
        'cheapest_total_cost': cheapest_total_cost,
        'total_potential_savings': total_potential_savings,
        'avg_rate': avg_rate,
        'avg_cheapest_rate': avg_cheapest_rate,
        'unique_lanes': final_filtered_data['Lane'].nunique(),
        'unique_scacs': final_filtered_data['Dray SCAC(FL)'].nunique(),
        'total_containers': final_filtered_data['Container Count'].sum()
    }
    
    # Calculate highest performance cost if performance data available
    highest_perf_cost, _ = calculate_performance_optimization(final_filtered_data)
    metrics['highest_perf_cost'] = highest_perf_cost
    
    # Calculate optimized cost using linear programming if data allows it
    current_cost_weight = st.session_state.get('cost_weight', 0.7)
    current_performance_weight = st.session_state.get('performance_weight', 0.3)
    
    # Store current weights for display regardless of optimization availability
    metrics['optimization_cost_weight'] = current_cost_weight
    metrics['optimization_performance_weight'] = current_performance_weight
    
    # Check if optimization is possible (performance data available)
    optimization_possible = False
    if ('Performance_Score' in final_filtered_data.columns and 
        len(final_filtered_data) > 0 and
        final_filtered_data['Performance_Score'].notna().sum() > 0):
        
        # Optimization is possible if we have performance data, regardless of carrier count
        # For single carrier lanes, we'll just use that carrier's cost
        optimization_possible = True
    
    if optimization_possible:
        # Try to get optimization results with current filter and current weights
        optimization_results = get_optimization_results(final_filtered_data, current_cost_weight, current_performance_weight)
        if optimization_results is not None and len(optimization_results) > 0:
            optimized_cost = optimization_results['Total Rate'].sum()
            metrics['optimized_cost'] = optimized_cost
            metrics['optimization_savings'] = total_cost - optimized_cost
            metrics['optimization_available'] = True
        else:
            # Optimization calculation failed
            metrics['optimized_cost'] = total_cost
            metrics['optimization_savings'] = 0
            metrics['optimization_available'] = False
    else:
        # Optimization not possible with current data
        metrics['optimized_cost'] = total_cost
        metrics['optimization_savings'] = 0
        metrics['optimization_available'] = False
    
    return metrics

def identify_suboptimal_selections(final_filtered_data):
    """Identify lanes where current selection is both higher cost AND lower performance than alternatives"""
    if 'Performance_Score' not in final_filtered_data.columns:
        return pd.DataFrame()
    
    suboptimal_selections = []
    
    for (lane, week), group in final_filtered_data.groupby(['Lane', 'Week Number']):
        if len(group) > 1:
            current = group.iloc[0]
            current_rate = current['Base Rate']
            current_perf = current.get('Performance_Score', 0) if pd.notna(current.get('Performance_Score', 0)) else 0
            current_scac = current['Dray SCAC(FL)']
            
            # Find alternatives with both better performance AND lower cost
            for _, alt in group.iterrows():
                alt_rate = alt['Base Rate']
                alt_perf = alt.get('Performance_Score', 0) if pd.notna(alt.get('Performance_Score', 0)) else 0
                
                if (alt['Dray SCAC(FL)'] != current_scac and 
                    alt_rate < current_rate and 
                    alt_perf > current_perf):
                    
                    suboptimal_selections.append({
                        'Lane': lane,
                        'Week_Number': week,
                        'Current_SCAC': current_scac,
                        'Current_Rate': current_rate,
                        'Current_Performance': current_perf,
                        'Container_Count': current['Container Count'],
                        'Best_Alternative_SCAC': alt['Dray SCAC(FL)'],
                        'Best_Alternative_Rate': alt_rate,
                        'Best_Alternative_Performance': alt_perf,
                        'Potential_Cost_Savings': (current_rate - alt_rate) * current['Container Count'],
                        'Performance_Improvement': alt_perf - current_perf
                    })
                    break  # Take first better alternative found
    
    return pd.DataFrame(suboptimal_selections)

def display_current_metrics(metrics):
    """Display the main metrics dashboard with enhanced styling and optimization cost"""
    if metrics is None:
        st.warning("⚠️ No data matches your selection.")
        return
        
    section_header("� Cost Analysis Dashboard")
    
    # Cost comparison section with improved styling
    st.markdown("### 💰 **Cost Strategy Comparison**")
    
    # Create cost comparison cards
    cost_col1, cost_col2, cost_col3, cost_col4 = st.columns(4)
    
    with cost_col1:
        st.markdown("""
        <div style="background-color: #f0f2f6; padding: 15px; border-radius: 10px; margin: 5px 0;">
            <h4 style="color: #1f77b4; margin: 0;">📋 Current Selection</h4>
            <h2 style="color: #1f77b4; margin: 5px 0;">${:,.2f}</h2>
            <p style="margin: 0; color: #666;">Your current carrier choices</p>
        </div>
        """.format(metrics['total_cost']), unsafe_allow_html=True)
    
    with cost_col2:
        cheapest_savings = metrics['total_cost'] - metrics['cheapest_total_cost']
        cheapest_pct = (cheapest_savings / metrics['total_cost'] * 100) if metrics['total_cost'] > 0 else 0
        savings_color = "#28a745" if cheapest_savings > 0 else "#6c757d"
        
        st.markdown("""
        <div style="background-color: #e8f5e8; padding: 15px; border-radius: 10px; margin: 5px 0;">
            <h4 style="color: #28a745; margin: 0;">💵 Cheapest Strategy</h4>
            <h2 style="color: #28a745; margin: 5px 0;">${:,.2f}</h2>
            <p style="margin: 0; color: {};">Save ${:,.2f} ({:.1f}%)</p>
        </div>
        """.format(metrics['cheapest_total_cost'], savings_color, cheapest_savings, cheapest_pct), unsafe_allow_html=True)
    
    with cost_col3:
        if metrics['optimization_available']:
            opt_savings = metrics['optimization_savings']
            opt_pct = (opt_savings / metrics['total_cost'] * 100) if metrics['total_cost'] > 0 else 0
            opt_savings_color = "#28a745" if opt_savings > 0 else "#6c757d"
            
            # Show optimization results with current weights
            cost_w = metrics['optimization_cost_weight']
            perf_w = metrics['optimization_performance_weight']
            weight_info = f"<br><small>Weights: {cost_w:.0%} cost, {perf_w:.0%} performance</small>"
            
            st.markdown("""
            <div style="background-color: #e6f7ff; padding: 15px; border-radius: 10px; margin: 5px 0;">
                <h4 style="color: #17a2b8; margin: 0;">🧮 Optimized Strategy</h4>
                <h2 style="color: #17a2b8; margin: 5px 0;">${:,.2f}</h2>
                <p style="margin: 0; color: {};">Save ${:,.2f} ({:.1f}%){}</p>
            </div>
            """.format(metrics['optimized_cost'], opt_savings_color, opt_savings, opt_pct, weight_info), unsafe_allow_html=True)
        else:
            # Show current weights and explain why optimization isn't available
            current_cost_w = metrics['optimization_cost_weight']
            current_perf_w = metrics['optimization_performance_weight']
            weight_info = f"<br><small>Weights: {current_cost_w:.0%} cost, {current_perf_w:.0%} performance</small>"
            
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; margin: 5px 0; border: 2px dashed #dee2e6;">
                <h4 style="color: #6c757d; margin: 0;">🧮 Optimized Strategy</h4>
                <h2 style="color: #6c757d; margin: 5px 0;">Not Available</h2>
                <p style="margin: 0; color: #6c757d;">Requires performance data & multiple carriers{}</p>
            </div>
            """.format(weight_info), unsafe_allow_html=True)
    
    with cost_col4:
        if metrics['highest_perf_cost'] > 0:
            perf_diff = metrics['total_cost'] - metrics['highest_perf_cost']
            perf_pct = (perf_diff / metrics['total_cost'] * 100) if metrics['total_cost'] > 0 else 0
            perf_color = "#ff6b6b" if perf_diff < 0 else "#28a745"
            
            st.markdown("""
            <div style="background-color: #fff0e6; padding: 15px; border-radius: 10px; margin: 5px 0;">
                <h4 style="color: #ff8c00; margin: 0;">🏆 Best Performance</h4>
                <h2 style="color: #ff8c00; margin: 5px 0;">${:,.2f}</h2>
                <p style="margin: 0; color: {};">{} ${:,.2f} ({:.1f}%)</p>
            </div>
            """.format(
                metrics['highest_perf_cost'], 
                perf_color,
                "Save" if perf_diff > 0 else "Cost",
                abs(perf_diff), 
                perf_pct
            ), unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 15px; border-radius: 10px; margin: 5px 0; border: 2px dashed #dee2e6;">
                <h4 style="color: #6c757d; margin: 0;">🏆 Best Performance</h4>
                <h2 style="color: #6c757d; margin: 5px 0;">N/A</h2>
                <p style="margin: 0; color: #6c757d;">No performance data</p>
            </div>
            """, unsafe_allow_html=True)
    
    # Divider
    st.markdown("---")
    
    # Average rates section
    st.markdown("### 📊 **Rate Analysis**")
    
    rate_col1, rate_col2, rate_col3 = st.columns(3)
    
    with rate_col1:
        st.metric(
            "📊 Average Current Rate", 
            f"${metrics['avg_rate']:.2f}",
            help="Average base rate across all your current selections"
        )
    
    with rate_col2:
        rate_diff = metrics['avg_rate'] - metrics['avg_cheapest_rate']
        st.metric(
            "📉 Average Cheapest Rate", 
            f"${metrics['avg_cheapest_rate']:.2f}",
            delta=f"-${rate_diff:.2f}",
            help="Average of cheapest available rates per lane"
        )
    
    with rate_col3:
        if metrics['optimization_available']:
            opt_avg_rate = metrics['optimized_cost'] / metrics['total_containers'] if metrics['total_containers'] > 0 else 0
            opt_rate_diff = metrics['avg_rate'] - opt_avg_rate
            st.metric(
                "🧮 Optimized Avg Rate",
                f"${opt_avg_rate:.2f}",
                delta=f"-${opt_rate_diff:.2f}",
                help="Average rate from linear programming optimization"
            )
        else:
            st.metric("🧮 Optimized Avg Rate", "N/A", help="Optimization not available")
    
    # Divider
    st.markdown("---")
    
    # Volume and scope metrics
    st.markdown("### 📈 **Scope & Volume**")
    
    scope_col1, scope_col2, scope_col3, scope_col4 = st.columns(4)
    
    with scope_col1:
        st.metric(
            "🛣️ Unique Lanes", 
            f"{metrics['unique_lanes']:,}",
            help="Number of unique origin-destination lane combinations"
        )
    
    with scope_col2:
        st.metric(
            "🚛 Unique Carriers", 
            f"{metrics['unique_scacs']:,}",
            help="Number of unique carriers (SCACs) in selection"
        )
    
    with scope_col3:
        st.metric(
            "📦 Total Containers", 
            f"{metrics['total_containers']:,}",
            help="Total container count across all selections"
        )
    
    with scope_col4:
        avg_containers_per_lane = metrics['total_containers'] / metrics['unique_lanes'] if metrics['unique_lanes'] > 0 else 0
        st.metric(
            "📊 Containers per Lane", 
            f"{avg_containers_per_lane:.1f}",
            help="Average containers per unique lane"
        )

    # Add explanation about cost comparisons
    with st.expander("ℹ️ **Understanding Cost Strategy Comparisons**"):
        st.markdown("""
        **� Current Selection**: Your actual carrier assignments and their costs.
        
        **💵 Cheapest Strategy**: What costs would be if you always picked the lowest-rate carrier for each lane (theoretical minimum, may sacrifice performance).
        
        **🧮 Optimized Strategy**: Mathematical optimization that balances cost savings with performance using linear programming. The weights used (cost vs performance priority) are shown below the cost. Default is 70% cost weight, 30% performance weight.
        
        **🏆 Best Performance Strategy**: What costs would be if you always picked the highest-performing carrier (may be more expensive but better service).
        
        ---
        
        **Why optimization can beat "cheapest":**
        - "Cheapest" uses lane minimums even if not available every week
        - "Optimized" uses actual week-specific rate availability 
        - "Optimized" considers performance trade-offs for better overall value
        
        **💡 Tip**: The optimized strategy often provides the best real-world balance of cost and service quality.
        """)

def show_detailed_analysis_table(final_filtered_data, metrics=None):
    """Show detailed analysis table with optimization strategy selectors"""
    section_header("📋 Detailed Analysis Table")
    
    # Create a unique key for the current data state to detect when data changes
    data_key = f"{len(final_filtered_data)}_{final_filtered_data['Total Rate'].sum():.2f}"
    
    # Initialize session state for scenarios if not exists or data changed
    if 'analysis_scenarios' not in st.session_state or st.session_state.get('data_key') != data_key:
        
        # Pre-calculate all scenarios to avoid reloading
        scenarios = {}
        
        # Base columns for all strategies
        base_columns = ['Discharged Port', 'Dray SCAC(FL)', 'Lane', 'Facility', 
                       'Week Number', 'Container Count']
        
        # 1. Current Selection
        current_columns = base_columns + ['Base Rate', 'Total Rate']
        if 'Performance_Score' in final_filtered_data.columns:
            current_columns.append('Performance_Score')
        
        current_data = final_filtered_data[current_columns].copy()
        if 'Performance_Score' in current_data.columns:
            current_data = current_data.rename(columns={'Performance_Score': 'Carrier Performance'})
        
        scenarios['Current Selection'] = {
            'data': current_data,
            'filename': 'current_selection_analysis.csv',
            'description': "📊 Showing your current carrier selections with rates and performance.",
            'cost_column': 'Total Rate'
        }
        
        # 2. Cheapest Cost
        cheapest_columns = base_columns + ['Cheapest Base Rate', 'Cheapest Total Rate', 'Potential Savings', 'Savings Percentage']
        cheapest_data = final_filtered_data[cheapest_columns].copy()
        cheapest_data = cheapest_data.rename(columns={
            'Cheapest Base Rate': 'Hypothetical Base Rate',
            'Cheapest Total Rate': 'Hypothetical Total Cost'
        })
        
        scenarios['Cheapest Cost'] = {
            'data': cheapest_data,
            'filename': 'cheapest_cost_scenario.csv',
            'description': "💰 **Hypothetical Scenario**: What if we moved ALL volume to the cheapest available carriers for each lane-week.",
            'cost_column': 'Hypothetical Total Cost'
        }
        
        # 3. Highest Performance (calculate using performance calculator)
        _, performance_data_list = calculate_performance_optimization(final_filtered_data)
        
        if performance_data_list:
            hp_data = []
            base_columns_set = set(base_columns)
            
            for perf_data in performance_data_list:
                # Create a row that matches the structure expected by the display
                hp_row = {}
                
                # Map performance calculator output to display format
                hp_row['Discharged Port'] = perf_data['Discharged_Port']
                hp_row['Dray SCAC(FL)'] = perf_data['Dray_SCAC']
                hp_row['Lane'] = perf_data['Lane']
                hp_row['Facility'] = perf_data['Facility']
                hp_row['Week Number'] = perf_data['Week_Number']
                hp_row['Container Count'] = perf_data['Container_Count']
                hp_row['Hypothetical_Carrier'] = perf_data['Best_Performance_Carrier']
                hp_row['Hypothetical_Base_Rate'] = perf_data['Best_Performance_Rate']
                hp_row['Hypothetical_Total_Cost'] = perf_data['Hypothetical_Total_Cost']
                hp_row['Hypothetical_Performance'] = perf_data['Best_Performance_Score']
                hp_row['Cost_Difference'] = perf_data['Cost_Difference']
                hp_row['Performance_Difference'] = perf_data['Performance_Difference']
                hp_row['Performance_Source'] = perf_data['Best_Performance_Source']
                
                hp_data.append(hp_row)
        else:
            # No performance data at all, use current rates
            for _, current in final_filtered_data.iterrows():
                hp_row = current.copy()
                hp_row['Hypothetical_Carrier'] = current['Dray SCAC(FL)']
                hp_row['Hypothetical_Base_Rate'] = current['Base Rate']
                hp_row['Hypothetical_Total_Cost'] = current['Total Rate']
                hp_row['Hypothetical_Performance'] = 0
                hp_row['Cost_Difference'] = 0
                hp_row['Performance_Difference'] = 0
                hp_row['Performance_Source'] = 'No Performance Data'
                
                hp_data.append(hp_row)

        if hp_data:
            hp_df = pd.DataFrame(hp_data)
            hp_columns = base_columns + ['Hypothetical_Carrier', 'Hypothetical_Base_Rate', 
                                       'Hypothetical_Total_Cost', 'Hypothetical_Performance', 
                                       'Cost_Difference', 'Performance_Difference', 'Performance_Source']
            
            hp_display_data = hp_df[hp_columns].copy()
            hp_display_data = hp_display_data.rename(columns={
                'Hypothetical_Carrier': 'Best Performance Carrier',
                'Hypothetical_Base_Rate': 'HP Base Rate',
                'Hypothetical_Total_Cost': 'HP Total Cost',
                'Hypothetical_Performance': 'HP Performance Score',
                'Cost_Difference': 'Cost Impact',
                'Performance_Difference': 'Performance Gain',
                'Performance_Source': 'Performance Data Source'
            })
            
            scenarios['Highest Performance'] = {
                'data': hp_display_data,
                'filename': 'highest_performance_scenario.csv',
                'description': "🏆 **Hypothetical Scenario**: For each lane-week, ALL volume goes to the highest performing carrier. Uses volume-weighted average performance when actual weekly performance is missing.",
                'cost_column': 'HP Total Cost'
            }
        
        # 4. Optimized (Linear Programming)
        # Use current slider weights for optimization results
        current_cost_weight = st.session_state.get('cost_weight', 0.7)
        current_performance_weight = st.session_state.get('performance_weight', 0.3)
        
        optimization_results = get_optimization_results(final_filtered_data, current_cost_weight, current_performance_weight)
        if optimization_results is not None and len(optimization_results) > 0:
            opt_data = optimization_results.copy()
            opt_data = opt_data.rename(columns={'Performance_Score': 'Optimized Performance'})
            
            # Add weight info to description
            weight_desc = f"(Current weights: {current_cost_weight:.0%} cost, {current_performance_weight:.0%} performance)"
            
            scenarios['Optimized'] = {
                'data': opt_data,
                'filename': 'optimized_assignments.csv',
                'description': f"🧮 **Linear Programming Optimization**: Optimal balance using current slider settings {weight_desc}. Mathematical optimization balances cost and performance.",
                'cost_column': 'Total Rate'
            }
        else:
            # Fallback if optimization fails
            scenarios['Optimized'] = {
                'data': current_data.copy(),
                'filename': 'optimized_fallback.csv',
                'description': f"🧮 **Optimization Not Available**: Current weights: {current_cost_weight:.0%} cost, {current_performance_weight:.0%} performance. Requires performance data and multiple carrier options per lane-week. Showing current selection instead.",
                'cost_column': 'Total Rate'
            }
        
        # Store scenarios in session state
        st.session_state.analysis_scenarios = scenarios
        st.session_state.data_key = data_key
    
    # Get scenarios from session state
    scenarios = st.session_state.analysis_scenarios
    
    # Strategy selector - use session state to avoid reloading
    if 'selected_strategy' not in st.session_state:
        st.session_state.selected_strategy = "Current Selection"
    
    strategy_options = list(scenarios.keys())
    
    selected_strategy = st.selectbox(
        "📊 Select Analysis Strategy:",
        strategy_options,
        index=strategy_options.index(st.session_state.selected_strategy) if st.session_state.selected_strategy in strategy_options else 0,
        key='strategy_selector',
        help="Choose which optimization strategy to view and download"
    )
    
    # Update session state
    st.session_state.selected_strategy = selected_strategy
    
    # Get the selected scenario (now from cached session state)
    scenario = scenarios[selected_strategy]
    display_data = scenario['data'].copy()
    filename = scenario['filename']
    description = scenario['description']
    cost_column = scenario['cost_column']
    
    # Display description
    st.info(description)
    
    # Sort appropriately based on available columns
    if selected_strategy == "Cheapest Cost" and 'Potential Savings' in display_data.columns:
        display_data = display_data.sort_values('Potential Savings', ascending=False)
    elif selected_strategy == "Highest Performance" and 'Performance Gain' in display_data.columns:
        display_data = display_data.sort_values('Performance Gain', ascending=False)
    elif selected_strategy == "Optimized":
        display_data = display_data.sort_values(['Discharged Port', 'Lane', 'Week Number'])
    else:
        display_data = display_data.sort_values(['Lane', 'Week Number'])
    
    # Display the table
    st.dataframe(display_data, use_container_width=True)
    
    # Show summary stats
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📊 Total Records", len(display_data))
    with col2:
        if 'Container Count' in display_data.columns:
            st.metric("📦 Total Containers", f"{display_data['Container Count'].sum():,}")
    with col3:
        # Calculate total cost using the appropriate column
        if cost_column in display_data.columns:
            total_cost = display_data[cost_column].sum()
            if selected_strategy in ["Cheapest Cost", "Highest Performance"]:
                st.metric("💰 Hypothetical Total Cost", f"${total_cost:,.2f}")
            else:
                st.metric("💰 Total Cost", f"${total_cost:,.2f}")
    
    # Download button
    if len(display_data) > 0:
        csv = display_data.to_csv(index=False)
        st.download_button(
            label=f"📥 Download {selected_strategy} Data",
            data=csv,
            file_name=filename,
            mime='text/csv',
            use_container_width=True
        )

def show_top_savings_opportunities(final_filtered_data):
    """Show top savings opportunities"""
    section_header("🎯 Top Savings Opportunities")
    
    columns = ['Lane', 'Dray SCAC(FL)', 'Week Number', 'Container Count', 
               'Base Rate', 'Cheapest Base Rate', 'Potential Savings', 'Savings Percentage']
    
    if 'Performance_Score' in final_filtered_data.columns:
        columns.append('Performance_Score')
        
    top_savings = final_filtered_data.nlargest(10, 'Potential Savings')[columns]
    
    if 'Performance_Score' in top_savings.columns:
        top_savings = top_savings.rename(columns={'Performance_Score': 'Carrier Performance'})
        
    st.dataframe(top_savings, use_container_width=True)

def show_complete_data_export(final_filtered_data):
    """Show complete data export section"""
    section_header("📄 Complete Data Export")
    
    if st.checkbox("🔍 Show Complete Data Table"):
        st.dataframe(final_filtered_data, use_container_width=True)

    if len(final_filtered_data) > 0:
        csv = final_filtered_data.to_csv(index=False)
        st.download_button(
            label="📥 Download comprehensive filtered data as CSV",
            data=csv,
            file_name='comprehensive_carrier_data.csv',
            mime='text/csv',
            use_container_width=True
        )

def show_suboptimal_analysis(final_filtered_data):
    """Display analysis of suboptimal selections"""
    section_header("🚨 Suboptimal Selection Analysis")
    
    suboptimal_df = identify_suboptimal_selections(final_filtered_data)
    
    if len(suboptimal_df) == 0:
        st.success("✅ **Great News!** No instances found where you're using higher cost AND lower performance carriers simultaneously.")
        return
    
    # Summary metrics
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("🚨 Suboptimal Selections", f"{len(suboptimal_df)}")
    
    with col2:
        total_wasted = suboptimal_df['Potential_Cost_Savings'].sum()
        st.metric("💸 Total Wasted Cost", f"${total_wasted:,.2f}")
    
    with col3:
        avg_perf_loss = suboptimal_df['Performance_Improvement'].mean()
        st.metric("📉 Avg Performance Loss", f"{avg_perf_loss:.2%}")
    
    # Show top issues
    st.markdown("### 🎯 **Top Priority Fixes**")
    priority_fixes = suboptimal_df.nlargest(10, 'Potential_Cost_Savings')
    
    # Format for display
    display_df = priority_fixes.copy()
    display_df['Current_Performance'] = display_df['Current_Performance'].apply(lambda x: f"{x:.1%}")
    display_df['Best_Alternative_Performance'] = display_df['Best_Alternative_Performance'].apply(lambda x: f"{x:.1%}")
    display_df['Performance_Improvement'] = display_df['Performance_Improvement'].apply(lambda x: f"+{x:.1%}")
    display_df['Potential_Cost_Savings'] = display_df['Potential_Cost_Savings'].apply(lambda x: f"${x:,.2f}")
    
    st.dataframe(display_df, use_container_width=True)
    
    # Export option
    if len(suboptimal_df) > 0:
        csv = suboptimal_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Suboptimal Selections Report",
            data=csv,
            file_name='suboptimal_carrier_selections.csv',
            mime='text/csv'
        )

def show_performance_score_analysis(final_filtered_data):
    """Show detailed analysis of performance scores assigned to each carrier by week"""
    section_header("🎯 Performance Score Analysis")
    
    if 'Performance_Score' not in final_filtered_data.columns:
        st.warning("⚠️ No performance data available for analysis.")
        return
    
    # Analysis tabs
    tab1, tab2, tab3 = st.tabs(["📊 Carrier Summary", "📅 Weekly Breakdown", "📈 Score Distribution"])
    
    with tab1:
        st.markdown("### 📊 **Carrier Performance Summary**")
        
        # Create carrier performance summary
        carrier_summary = final_filtered_data.groupby('Dray SCAC(FL)').agg({
            'Performance_Score': ['mean', 'min', 'max', 'std', 'count'],
            'Container Count': 'sum',
            'Lane': 'nunique',
            'Week Number': 'nunique'
        }).round(4)  # More decimal places for better precision
        
        # Flatten column names
        carrier_summary.columns = ['Avg_Performance', 'Min_Performance', 'Max_Performance', 'Std_Performance', 'Record_Count', 'Total_Containers', 'Unique_Lanes', 'Unique_Weeks']
        carrier_summary = carrier_summary.reset_index()
        
        # Convert performance scores to percentage format for display
        perf_columns = ['Avg_Performance', 'Min_Performance', 'Max_Performance', 'Std_Performance']
        for col in perf_columns:
            carrier_summary[f'{col}_Display'] = carrier_summary[col].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "N/A")
        
        # Create display version
        display_summary = carrier_summary[['Dray SCAC(FL)', 'Avg_Performance_Display', 'Min_Performance_Display', 'Max_Performance_Display', 'Std_Performance_Display', 'Record_Count', 'Total_Containers', 'Unique_Lanes', 'Unique_Weeks']].copy()
        display_summary.columns = ['Carrier', 'Avg Performance', 'Min Performance', 'Max Performance', 'Std Deviation', 'Record Count', 'Total Containers', 'Unique Lanes', 'Unique Weeks']
        
        # Add performance consistency indicator
        carrier_summary['Consistency'] = carrier_summary.apply(
            lambda x: "High" if x['Std_Performance'] < 0.05 else ("Medium" if x['Std_Performance'] < 0.10 else "Low"), 
            axis=1
        )
        display_summary['Consistency'] = carrier_summary['Consistency']
        
        # Sort by average performance (using original numeric values)
        carrier_summary = carrier_summary.sort_values('Avg_Performance', ascending=False)
        display_summary = display_summary.iloc[carrier_summary.index]
        
        # Display the summary table
        st.dataframe(display_summary, use_container_width=True)
        
        # Download option for carrier summary (use original numeric values)
        if len(carrier_summary) > 0:
            csv_carrier = carrier_summary[['Dray SCAC(FL)', 'Avg_Performance', 'Min_Performance', 'Max_Performance', 'Std_Performance', 'Record_Count', 'Total_Containers', 'Unique_Lanes', 'Unique_Weeks', 'Consistency']].to_csv(index=False)
            st.download_button(
                label="📥 Download Carrier Performance Summary",
                data=csv_carrier,
                file_name='carrier_performance_summary.csv',
                mime='text/csv'
            )
    
    with tab2:
        st.markdown("### 📅 **Weekly Performance Breakdown**")
        
        # Create carrier selector
        selected_carriers = st.multiselect(
            "🚛 Select Carriers to Analyze:",
            options=sorted(final_filtered_data['Dray SCAC(FL)'].unique()),
            default=sorted(final_filtered_data['Dray SCAC(FL)'].unique()),  # Default to all carriers
            help="Select specific carriers to see their weekly performance breakdown"
        )
        
        if selected_carriers:
            # Filter data for selected carriers
            filtered_for_analysis = final_filtered_data[
                final_filtered_data['Dray SCAC(FL)'].isin(selected_carriers)
            ]
            
            # Create pivot table showing performance by carrier and week
            weekly_pivot = filtered_for_analysis.pivot_table(
                values='Performance_Score',
                index='Dray SCAC(FL)',
                columns='Week Number',
                aggfunc='mean',
                fill_value=None
            )
            
            # Convert to percentage format for display
            weekly_pivot_display = weekly_pivot.copy()
            for col in weekly_pivot_display.columns:
                weekly_pivot_display[col] = weekly_pivot_display[col].apply(
                    lambda x: f"{x:.1%}" if pd.notna(x) else ""
                )
            
            st.markdown("**Performance Score by Carrier and Week (%):**")
            st.dataframe(weekly_pivot_display, use_container_width=True)
            
            # Show detailed records for selected carriers
            st.markdown("**Detailed Records:**")
            detailed_columns = ['Dray SCAC(FL)', 'Lane', 'Week Number', 'Performance_Score', 
                              'Container Count', 'Base Rate', 'Discharged Port', 'Facility']
            
            detailed_records = filtered_for_analysis[detailed_columns].copy().sort_values(
                ['Dray SCAC(FL)', 'Week Number', 'Lane']
            )
            
            # Format performance score as percentage for display
            detailed_records['Performance %'] = detailed_records['Performance_Score'].apply(
                lambda x: f"{x:.1%}" if pd.notna(x) else ""
            )
            
            # Create display version without the original Performance_Score column
            display_columns = ['Dray SCAC(FL)', 'Lane', 'Week Number', 'Performance %', 
                              'Container Count', 'Base Rate', 'Discharged Port', 'Facility']
            detailed_display = detailed_records[['Dray SCAC(FL)', 'Lane', 'Week Number', 'Performance %', 
                              'Container Count', 'Base Rate', 'Discharged Port', 'Facility']]
            
            st.dataframe(detailed_display, use_container_width=True)
            
            # Download option for weekly analysis (use original numeric values)
            csv_weekly = detailed_records.drop('Performance %', axis=1).to_csv(index=False)
            st.download_button(
                label="📥 Download Weekly Performance Analysis",
                data=csv_weekly,
                file_name='weekly_performance_analysis.csv',
                mime='text/csv'
            )
        else:
            st.info("👆 Select carriers above to see their weekly performance breakdown")
    
    with tab3:
        st.markdown("### 📈 **Performance Score Distribution**")
        
        # Performance score statistics
        perf_stats_col1, perf_stats_col2, perf_stats_col3, perf_stats_col4 = st.columns(4)
        
        with perf_stats_col1:
            avg_perf = final_filtered_data['Performance_Score'].mean()
            st.metric("📊 Average Score", f"{avg_perf:.3f}")
        
        with perf_stats_col2:
            std_perf = final_filtered_data['Performance_Score'].std()
            st.metric("📏 Standard Deviation", f"{std_perf:.3f}")
        
        with perf_stats_col3:
            min_perf = final_filtered_data['Performance_Score'].min()
            max_perf = final_filtered_data['Performance_Score'].max()
            st.metric("📉 Min Score", f"{min_perf:.3f}")
            st.metric("📈 Max Score", f"{max_perf:.3f}")
        
        with perf_stats_col4:
            # Count how many records have very low scores (might be filled with global average)
            low_score_threshold = 0.1
            low_scores = (final_filtered_data['Performance_Score'] <= low_score_threshold).sum()
            st.metric("⚠️ Very Low Scores", f"{low_scores}")
            st.caption(f"(≤ {low_score_threshold})")
        
        # Performance score ranges
        st.markdown("**Performance Score Ranges:**")
        
        # Create performance buckets
        def categorize_performance(score):
            if pd.isna(score):
                return "Missing"
            elif score <= 0.1:
                return "Very Low (≤0.1)"
            elif score <= 0.3:
                return "Low (0.1-0.3)"
            elif score <= 0.6:
                return "Medium (0.3-0.6)"
            elif score <= 0.8:
                return "High (0.6-0.8)"
            else:
                return "Very High (>0.8)"
        
        final_filtered_data_copy = final_filtered_data.copy()
        final_filtered_data_copy['Performance_Category'] = final_filtered_data_copy['Performance_Score'].apply(categorize_performance)
        
        # Show distribution by category
        perf_distribution = final_filtered_data_copy.groupby('Performance_Category').agg({
            'Dray SCAC(FL)': 'nunique',
            'Container Count': 'sum',
            'Performance_Score': ['count', 'mean']
        }).round(3)
        
        perf_distribution.columns = ['Unique_Carriers', 'Total_Containers', 'Record_Count', 'Avg_Score_In_Category']
        perf_distribution = perf_distribution.reset_index()
        
        st.dataframe(perf_distribution, use_container_width=True)
        
        # Identify potential data quality issues
        st.markdown("### 🔍 **Data Quality Assessment**")
        
        # Check for carriers with identical performance scores (might indicate filled values)
        identical_scores = final_filtered_data.groupby(['Dray SCAC(FL)', 'Performance_Score']).size().reset_index(name='Count')
        carriers_with_identical = identical_scores[identical_scores['Count'] > 5]  # More than 5 identical scores
        
        if len(carriers_with_identical) > 0:
            st.warning("⚠️ **Potential Filled Performance Scores Detected**")
            st.markdown("The following carriers have many identical performance scores, which may indicate calculated/filled values:")
            
            identical_summary = carriers_with_identical.merge(
                carrier_summary[['Dray SCAC(FL)', 'Record_Count', 'Unique_Weeks']],
                on='Dray SCAC(FL)'
            ).sort_values('Count', ascending=False)
            
            st.dataframe(identical_summary, use_container_width=True)
        else:
            st.success("✅ **Good Performance Score Variety**: No carriers show excessive identical performance scores")

def show_carrier_performance_matrix(final_filtered_data):
    """Show a matrix of carrier performance vs cost to identify patterns"""
    section_header("📊 Carrier Performance vs Cost Matrix")
    
    if 'Performance_Score' not in final_filtered_data.columns:
        st.warning("⚠️ Performance data not available for matrix analysis.")
        return
    
    # Create carrier summary
    carrier_summary = final_filtered_data.groupby('Dray SCAC(FL)').agg({
        'Base Rate': 'mean',
        'Performance_Score': 'mean',
        'Container Count': 'sum',
        'Total Rate': 'sum'
    }).reset_index()
    
    # Categorize carriers
    carrier_summary['Cost_Level'] = pd.qcut(carrier_summary['Base Rate'], 2, labels=['Low Cost', 'High Cost'])
    carrier_summary['Perf_Level'] = pd.qcut(carrier_summary['Performance_Score'], 2, labels=['Low Perf', 'High Perf'])
    
    # Create categories
    matrix_data = []
    for _, carrier in carrier_summary.iterrows():
        if carrier['Cost_Level'] == 'Low Cost' and carrier['Perf_Level'] == 'High Perf':
            category = "🌟 IDEAL"
        elif carrier['Cost_Level'] == 'High Cost' and carrier['Perf_Level'] == 'Low Perf':
            category = "🚨 AVOID"
        elif carrier['Cost_Level'] == 'Low Cost':
            category = "💰 COST FOCUSED"
        else:
            category = "⭐ PERFORMANCE FOCUSED"
        
        matrix_data.append({
            'Carrier': carrier['Dray SCAC(FL)'],
            'Avg_Rate': f"${carrier['Base Rate']:.2f}",
            'Avg_Performance': f"{carrier['Performance_Score']:.1%}",
            'Total_Containers': carrier['Container Count'],
            'Category': category
        })
    
    matrix_df = pd.DataFrame(matrix_data)
    
    # Display by category
    for category in sorted(matrix_df['Category'].unique()):
        st.markdown(f"**{category}**")
        category_data = matrix_df[matrix_df['Category'] == category]
        st.dataframe(category_data[['Carrier', 'Avg_Rate', 'Avg_Performance', 'Total_Containers']], 
                    use_container_width=True, hide_index=True)
