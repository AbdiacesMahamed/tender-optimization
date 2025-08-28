"""
Linear Programming optimization module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
import numpy as np
import pulp as pulp
from .config_styling import section_header

def show_optimization_section(final_filtered_data):
    """Display the Linear Programming optimization interface"""
    section_header("🧮 Linear Programming Optimization")

    if 'Performance_Score' in final_filtered_data.columns and len(final_filtered_data) > 0:
        st.markdown("**Find the optimal balance between cost savings and carrier performance using linear programming.**")
        
        # Check if we have performance data in filtered results
        perf_data_available = final_filtered_data['Performance_Score'].notna().sum()
        
        if perf_data_available == 0:
            st.warning("⚠️ No performance data found in filtered results. The optimization requires performance scores.")
            return
        
        # Check carrier distribution
        lane_week_counts = final_filtered_data.groupby(['Lane', 'Week Number']).size()
        multi_carrier_lanes = lane_week_counts[lane_week_counts > 1]
        single_carrier_lanes = lane_week_counts[lane_week_counts == 1]
        
        # Show optimization context
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Multi-Carrier Lanes", len(multi_carrier_lanes), help="Lanes with optimization choices")
        with col2:
            st.metric("Single-Carrier Lanes", len(single_carrier_lanes), help="Lanes with only one carrier option")
        
        if len(multi_carrier_lanes) == 0 and len(single_carrier_lanes) > 0:
            st.info("ℹ️ All lanes have only one carrier option. Optimization will show current selection costs.")
        elif len(multi_carrier_lanes) > 0:
            st.info(f"📊 Optimization will choose best carriers for {len(multi_carrier_lanes)} lanes and use default carriers for {len(single_carrier_lanes)} single-carrier lanes.")
        
        # Initialize session state for weights if not exists
        if 'cost_weight' not in st.session_state:
            st.session_state.cost_weight = 0.7
            st.session_state.performance_weight = 0.3
        
        # Optimization parameters (sliders) - using session state to prevent page reloads
        col1, col2 = st.columns(2)
        
        with col1:
            # Cost weight slider with callback to auto-adjust performance weight
            def update_performance_weight():
                st.session_state.performance_weight = 1.0 - st.session_state.cost_weight
            
            cost_weight = st.slider(
                "Cost Weight (importance)", 
                min_value=0.0, 
                max_value=1.0, 
                value=st.session_state.cost_weight,
                step=0.1,
                help="Higher values prioritize cost savings. Performance weight will auto-adjust to maintain sum = 1.0",
                key="cost_weight",
                on_change=update_performance_weight
            )
        
        with col2:
            # Performance weight slider with callback to auto-adjust cost weight
            def update_cost_weight():
                st.session_state.cost_weight = 1.0 - st.session_state.performance_weight
            
            performance_weight = st.slider(
                "Performance Weight (importance)", 
                min_value=0.0, 
                max_value=1.0, 
                value=st.session_state.performance_weight,
                step=0.1,
                help="Higher values prioritize carrier performance. Cost weight will auto-adjust to maintain sum = 1.0",
                key="performance_weight",
                on_change=update_cost_weight
            )
        
        # Run optimization button
        if st.button("🚀 Run Optimization", type="primary"):
            # Store the optimization results in session state for metrics display
            run_optimization(final_filtered_data, cost_weight, performance_weight)
    else:
        st.info("ℹ️ Linear programming optimization requires performance data. Please upload performance data to use this feature.")

def run_optimization(final_filtered_data, cost_weight, performance_weight):
    """Run the linear programming optimization"""
    with st.spinner("Running linear programming optimization..."):
        
        # Store weights in session state for metrics display
        st.session_state.optimization_cost_weight = cost_weight
        st.session_state.optimization_performance_weight = performance_weight
        
        # Prepare data for optimization
        opt_data = final_filtered_data.copy()
        
        # Verify that all performance scores are now filled
        missing_performance = opt_data['Performance_Score'].isna().sum()
        if missing_performance > 0:
            st.error(f"""
            ❌ **Data Pipeline Issue**: {missing_performance} rows still missing performance scores!
            
            The workflow should be:
            Raw Excel → data_loader.py → data_processor.py → apply_volume_weighted_performance → Final Data
            
            Missing performance scores indicate the volume-weighted performance calculation didn't run properly.
            """)
            return None
        
        if len(opt_data) == 0:
            st.error("❌ No data with performance scores available.")
            return
        
        # Check if we have multiple carriers per lane-week combination
        lane_week_counts = opt_data.groupby(['Lane', 'Week Number']).size()
        multi_carrier_lanes = lane_week_counts[lane_week_counts > 1]
        
        if len(multi_carrier_lanes) == 0:
            st.warning("⚠️ No lane-week combinations have multiple carrier options. Optimization requires choices between carriers.")
            return
        
        try:
            success, lane_week_carriers = perform_optimization(opt_data, cost_weight, performance_weight)
            
            if success:
                # Calculate optimization total cost for comparison
                total_opt_cost = 0
                for idx, row in lane_week_carriers.iterrows():
                    if row['choice_var'].varValue and row['choice_var'].varValue > 0.5:
                        total_opt_cost += row['Base Rate'] * row['Total_Lane_Volume']
                
                # Store optimization results in session state for metrics display
                st.session_state.optimization_cost = total_opt_cost
                st.session_state.optimization_available = True
                st.session_state.optimization_savings = final_filtered_data['Total Rate'].sum() - total_opt_cost
                
                st.success(f"✅ **Optimization Complete!** Total cost: ${total_opt_cost:,.2f}")
                st.info(f"💰 Savings vs current selection: ${st.session_state.optimization_savings:,.2f}")
            else:
                # Clear optimization results if failed
                st.session_state.optimization_available = False
                    
        except Exception as e:
            st.error(f"❌ Optimization error: {str(e)}")
            st.session_state.optimization_available = False

def perform_optimization(opt_data, cost_weight, performance_weight):
    """Perform the actual linear programming optimization with whole lane assignments"""
    
    # Aggregate data by Lane-Week-SCAC to get total volume per carrier per lane-week
    lane_week_carriers = opt_data.groupby(['Lane', 'Week Number', 'Dray SCAC(FL)']).agg({
        'Base Rate': 'first',
        'Performance_Score': 'first',
        'Container Count': 'sum',
        'Discharged Port': 'first',  # Include port information
        'Facility': 'first'  # Include facility information
    }).reset_index()
    
    # Get total volume for each lane-week combination
    lane_week_totals = opt_data.groupby(['Lane', 'Week Number'])['Container Count'].sum().reset_index()
    lane_week_totals = lane_week_totals.rename(columns={'Container Count': 'Total_Lane_Volume'})
    
    # Merge to get total lane volume for each carrier option
    lane_week_carriers = pd.merge(lane_week_carriers, lane_week_totals, on=['Lane', 'Week Number'])
    
    # Create optimization problem
    prob = LpProblem("Carrier_Lane_Optimization", LpMinimize)
    
    # Decision variables: binary variable for each carrier-lane-week combination
    choices = []
    for idx, row in lane_week_carriers.iterrows():
        var_name = f"assign_lane_{idx}"
        choices.append(LpVariable(var_name, cat='Binary'))
    
    lane_week_carriers['choice_var'] = choices
    
    # Setup optimization objective
    setup_optimization_objective(prob, lane_week_carriers, cost_weight, performance_weight)
    
    # Add constraints - one carrier per lane-week gets ALL volume
    add_optimization_constraints(prob, lane_week_carriers)
    
    # Solve the problem
    status = prob.solve(PULP_CBC_CMD(msg=0))
    
    # Display results
    if LpStatus[status] == 'Optimal':
        display_optimization_results(lane_week_carriers, opt_data)
        return True, lane_week_carriers
    else:
        st.error(f"❌ Optimization failed. Status: {LpStatus[status]}")
        return False, None

def setup_optimization_objective(prob, lane_week_carriers, cost_weight, performance_weight):
    """Setup the optimization objective function"""
    # Normalize costs and performance for objective function
    max_rate = lane_week_carriers['Base Rate'].max()
    min_rate = lane_week_carriers['Base Rate'].min()
    max_perf = lane_week_carriers['Performance_Score'].max()
    min_perf = lane_week_carriers['Performance_Score'].min()
    
    # Avoid division by zero
    rate_range = max_rate - min_rate if max_rate != min_rate else 1
    perf_range = max_perf - min_perf if max_perf != min_perf else 1
    
    # Normalized cost (0-1, where 0 is cheapest)
    lane_week_carriers['norm_cost'] = (lane_week_carriers['Base Rate'] - min_rate) / rate_range
    
    # Normalized performance (0-1, where 1 is best performance)
    lane_week_carriers['norm_performance'] = (lane_week_carriers['Performance_Score'] - min_perf) / perf_range
    
    # Normalize weights to sum to 1
    total_weight = cost_weight + performance_weight
    if total_weight > 0:
        norm_cost_weight = cost_weight / total_weight
        norm_performance_weight = performance_weight / total_weight
    else:
        norm_cost_weight = 0.5
        norm_performance_weight = 0.5
    
    # Objective function using TOTAL LANE VOLUME
    objective_terms = []
    for idx, row in lane_week_carriers.iterrows():
        # Cost component (minimize cost)
        cost_component = norm_cost_weight * row['norm_cost'] * row['Total_Lane_Volume']
        # Performance component (maximize performance, so subtract it)
        perf_component = norm_performance_weight * row['norm_performance'] * row['Total_Lane_Volume']
        
        objective_terms.append(row['choice_var'] * (cost_component - perf_component))
    
    prob += lpSum(objective_terms)

def add_optimization_constraints(prob, lane_week_carriers):
    """Add constraints for whole lane assignments"""
    # Constraints: exactly one carrier per lane-week combination gets ALL the volume
    for (lane, week), group in lane_week_carriers.groupby(['Lane', 'Week Number']):
        if len(group) > 1:  # Only add constraint if there are multiple carrier options
            prob += lpSum([row['choice_var'] for _, row in group.iterrows()]) == 1
        else:
            # If only one carrier option, force it to be selected
            prob += group.iloc[0]['choice_var'] == 1

def display_optimization_results(lane_week_carriers, opt_data):
    """Display the optimization results in one simple table"""
    st.success("✅ Optimization completed successfully!")
    
    # Get selected carriers for each lane-week
    selected_assignments = []
    for idx, row in lane_week_carriers.iterrows():
        if row['choice_var'].varValue and row['choice_var'].varValue > 0.5:  # Selected
            total_cost_for_lane = row['Base Rate'] * row['Total_Lane_Volume']
            
            selected_assignments.append({
                'Discharged Port': row['Discharged Port'],
                'Lane': row['Lane'],
                'Week Number': row['Week Number'],
                'Facility': row['Facility'],
                'Assigned SCAC': row['Dray SCAC(FL)'],
                'Base Rate': f"${row['Base Rate']:.2f}",
                'Performance Score': f"{row['Performance_Score']:.1f}%",
                'Total Containers': f"{row['Total_Lane_Volume']:,}",
                'Total Cost': f"${total_cost_for_lane:,.2f}"
            })
    
    if len(selected_assignments) == 0:
        st.error("❌ No carrier assignments were made.")
        return
    
    results_df = pd.DataFrame(selected_assignments)
    
    # Display the results table
    st.markdown("### 📋 Optimized Carrier Assignments")
    st.dataframe(results_df.sort_values(['Discharged Port', 'Lane', 'Week Number']), use_container_width=True)
    
    # Download button
    csv_data = results_df.to_csv(index=False)
    st.download_button(
        label="📥 Download Optimization Results",
        data=csv_data,
        file_name='linear_programming_results.csv',
        mime='text/csv',
        use_container_width=True
    )

def get_optimization_results(final_filtered_data, cost_weight=None, performance_weight=None):
    """Get optimization results without displaying them (for detailed analysis table)"""
    
    # Use stored weights from session state if available, otherwise use defaults
    if cost_weight is None and 'optimization_cost_weight' in st.session_state:
        cost_weight = st.session_state.optimization_cost_weight
    elif cost_weight is None:
        cost_weight = 0.7
        
    if performance_weight is None and 'optimization_performance_weight' in st.session_state:
        performance_weight = st.session_state.optimization_performance_weight
    elif performance_weight is None:
        performance_weight = 0.3
    
    # Use complete data - should have all performance scores filled
    opt_data = final_filtered_data.copy()
    
    # Verify data completeness
    missing_performance = opt_data['Performance_Score'].isna().sum()
    if missing_performance > 0:
        return None  # Data pipeline issue - performance scores should be filled
    
    if len(opt_data) == 0:
        return None
    
    # Check carrier distribution per lane-week
    lane_week_counts = opt_data.groupby(['Lane', 'Week Number']).size()
    multi_carrier_lanes = lane_week_counts[lane_week_counts > 1]
    single_carrier_lanes = lane_week_counts[lane_week_counts == 1]
    
    # Prepare result list
    selected_assignments = []
    
    # Handle multi-carrier lanes with optimization
    if len(multi_carrier_lanes) > 0:
        try:
            # Filter data to only multi-carrier lanes
            multi_carrier_data = opt_data[opt_data.set_index(['Lane', 'Week Number']).index.isin(multi_carrier_lanes.index)]
            
            # Aggregate data by Lane-Week-SCAC to get total volume per carrier per lane-week
            lane_week_carriers = multi_carrier_data.groupby(['Lane', 'Week Number', 'Dray SCAC(FL)']).agg({
                'Base Rate': 'first',
                'Performance_Score': 'first',
                'Container Count': 'sum',
                'Discharged Port': 'first',
                'Facility': 'first'
            }).reset_index()
            
            # Get total volume for each lane-week combination
            lane_week_totals = multi_carrier_data.groupby(['Lane', 'Week Number'])['Container Count'].sum().reset_index()
            lane_week_totals = lane_week_totals.rename(columns={'Container Count': 'Total_Lane_Volume'})
            
            # Merge to get total lane volume for each carrier option
            lane_week_carriers = pd.merge(lane_week_carriers, lane_week_totals, on=['Lane', 'Week Number'])
            
            # Create optimization problem
            prob = LpProblem("Carrier_Lane_Optimization", LpMinimize)
            
            # Decision variables: binary variable for each carrier-lane-week combination
            choices = []
            for idx, row in lane_week_carriers.iterrows():
                var_name = f"assign_lane_{idx}"
                choices.append(LpVariable(var_name, cat='Binary'))
            
            lane_week_carriers['choice_var'] = choices
            
            # Setup optimization objective
            setup_optimization_objective(prob, lane_week_carriers, cost_weight, performance_weight)
            
            # Add constraints - one carrier per lane-week gets ALL volume
            add_optimization_constraints(prob, lane_week_carriers)
            
            # Solve the problem
            status = prob.solve(PULP_CBC_CMD(msg=0))
            
            # Get results if optimal
            if LpStatus[status] == 'Optimal':
                for idx, row in lane_week_carriers.iterrows():
                    if row['choice_var'].varValue and row['choice_var'].varValue > 0.5:  # Selected
                        total_cost_for_lane = row['Base Rate'] * row['Total_Lane_Volume']
                        
                        selected_assignments.append({
                            'Discharged Port': row['Discharged Port'],
                            'Lane': row['Lane'],
                            'Week Number': row['Week Number'],
                            'Facility': row['Facility'],
                            'Dray SCAC(FL)': row['Dray SCAC(FL)'],
                            'Container Count': row['Total_Lane_Volume'],
                            'Base Rate': row['Base Rate'],
                            'Performance_Score': row['Performance_Score'],
                            'Total Rate': total_cost_for_lane
                        })
            else:
                return None  # Optimization failed
                
        except Exception as e:
            return None
    
    # Handle single carrier lanes (just use their only option)
    if len(single_carrier_lanes) > 0:
        single_carrier_data = opt_data[opt_data.set_index(['Lane', 'Week Number']).index.isin(single_carrier_lanes.index)]
        
        for (lane, week), group in single_carrier_data.groupby(['Lane', 'Week Number']):
            row = group.iloc[0]  # Take the only carrier for this lane-week
            total_containers = group['Container Count'].sum()
            total_cost_for_lane = row['Base Rate'] * total_containers
            
            selected_assignments.append({
                'Discharged Port': row['Discharged Port'],
                'Lane': lane,
                'Week Number': week,
                'Facility': row['Facility'],
                'Dray SCAC(FL)': row['Dray SCAC(FL)'],
                'Container Count': total_containers,
                'Base Rate': row['Base Rate'],
                'Performance_Score': row['Performance_Score'],
                'Total Rate': total_cost_for_lane
            })
    
    # Return results
    if selected_assignments:
        result_df = pd.DataFrame(selected_assignments)
        return result_df
    else:
        return None

def show_missing_rate_analysis_for_optimization(final_filtered_data, original_data=None):
    """Show missing rate analysis specifically for optimization context"""
    from .missing_rate_analysis import get_missing_rate_summary, show_missing_rate_dashboard_widget
    
    section_header("🔍 Missing Rate Analysis for Optimization")
    
    # Show the missing rate widget
    show_missing_rate_dashboard_widget(final_filtered_data, original_data)
    
    # Find lanes that have no rates at all (regardless of week)
    lanes_with_no_rates = []
    if len(final_filtered_data) > 0:
        # Group by lane and check if any records in that lane have valid rates
        lane_rate_status = final_filtered_data.groupby('Lane').agg({
            'Base Rate': lambda x: (x.notna() & (x > 0)).any(),  # True if any valid rate exists
            'Container Count': 'sum',
            'Week Number': 'nunique',
            'Dray SCAC(FL)': 'nunique'
        }).reset_index()
        
        # Find lanes where no valid rates exist
        lanes_with_no_rates = lane_rate_status[~lane_rate_status['Base Rate']]
        lanes_with_no_rates = lanes_with_no_rates.rename(columns={
            'Base Rate': 'Has_Valid_Rates',
            'Container Count': 'Total_Containers',
            'Week Number': 'Total_Weeks',
            'Dray SCAC(FL)': 'Total_Carriers'
        })
    
    # Additional optimization-specific analysis
    if 'Performance_Score' in final_filtered_data.columns:
        perf_missing = final_filtered_data['Performance_Score'].isna().sum()
        if perf_missing > 0:
            st.error(f"❌ **Critical for Optimization**: {perf_missing:,} records missing performance scores")
            st.markdown("""
            **Impact on Optimization:**
            - Records without performance scores are excluded from optimization
            - This creates an unfair comparison with cost scenarios
            - May result in optimization showing unrealistic savings
            """)
        else:
            st.success("✅ **Performance Data Complete**: All records have performance scores for optimization")
    
    # Check lane-week carrier availability for optimization
    lane_week_counts = final_filtered_data.groupby(['Lane', 'Week Number']).size()
    single_carrier_lanes = lane_week_counts[lane_week_counts == 1]
    multi_carrier_lanes = lane_week_counts[lane_week_counts > 1]
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "🛣️ Total Lane-Week Combinations",
            f"{len(lane_week_counts):,}",
            help="Total number of lane-week combinations in your data"
        )
    
    with col2:
        st.metric(
            "🚛 Single Carrier Only",
            f"{len(single_carrier_lanes):,}",
            help="Lane-weeks with only one carrier option (no optimization possible)"
        )
    
    with col3:
        st.metric(
            "🔄 Multiple Carriers",
            f"{len(multi_carrier_lanes):,}",
            help="Lane-weeks with multiple carrier options (optimization possible)"
        )
    
    if len(multi_carrier_lanes) == 0:
        st.warning("⚠️ **No optimization possible**: All lane-week combinations have only one carrier option")
    elif len(single_carrier_lanes) > len(multi_carrier_lanes):
        st.info(f"ℹ️ **Limited optimization scope**: Only {len(multi_carrier_lanes):,} out of {len(lane_week_counts):,} lane-weeks have multiple carriers")
    else:
        st.success(f"✅ **Good optimization potential**: {len(multi_carrier_lanes):,} lane-weeks have multiple carrier choices")
    
    # Show lanes with completely missing rates (no rates for any week)
    if len(lanes_with_no_rates) > 0:
        st.error(f"🚨 **Critical Issue**: {len(lanes_with_no_rates)} lanes have no valid rates for any week!")
        
        with st.expander("🚨 Lanes with No Valid Rates (Any Week)"):
            st.warning(f"Found {len(lanes_with_no_rates):,} lanes that have no valid rate data across all weeks")
            
            # Show affected lanes
            display_lanes = lanes_with_no_rates[['Lane', 'Total_Containers', 'Total_Weeks', 'Total_Carriers']].copy()
            display_lanes['Total_Containers'] = display_lanes['Total_Containers'].apply(lambda x: f"{x:,}")
            
            st.dataframe(display_lanes, use_container_width=True)
            
            # Calculate impact
            total_affected_containers = lanes_with_no_rates['Total_Containers'].sum()
            total_containers = final_filtered_data['Container Count'].sum()
            impact_pct = (total_affected_containers / total_containers * 100) if total_containers > 0 else 0
            
            st.error(f"""
            **Critical Impact:**
            - {total_affected_containers:,} containers affected ({impact_pct:.1f}% of total volume)
            - These lanes cannot be included in optimization calculations
            - Cost comparisons will be incomplete and potentially misleading
            """)
    
    # Show lanes with missing rates that might affect optimization
    rate_missing = final_filtered_data[
        (final_filtered_data['Base Rate'].isna()) | 
        (final_filtered_data['Base Rate'] <= 0)
    ]
    
    if len(rate_missing) > 0:
        with st.expander("⚠️ Records with Missing/Invalid Rate Data"):
            st.warning(f"Found {len(rate_missing):,} individual records with missing or zero rates")
            
            # Group by lane to show which lanes are affected
            lanes_affected = rate_missing.groupby('Lane').agg({
                'Dray SCAC(FL)': 'nunique',
                'Container Count': 'sum',
                'Week Number': 'nunique'
            }).reset_index()
            
            lanes_affected.columns = ['Lane', 'Carriers_Affected', 'Total_Containers', 'Weeks_Affected']
            lanes_affected = lanes_affected.sort_values('Total_Containers', ascending=False)
            
            # Format for display
            display_affected = lanes_affected.copy()
            display_affected['Total_Containers'] = display_affected['Total_Containers'].apply(lambda x: f"{x:,}")
            
            st.dataframe(display_affected, use_container_width=True)
            
            st.markdown("""
            **Impact on Optimization:**
            - These records may be excluded from optimization calculations
            - May result in incomplete cost comparisons
            - Consider reviewing data quality before running optimization
            """)
    
    # Summary of data quality for optimization
    st.markdown("### 📊 **Data Quality Summary for Optimization**")
    
    total_records = len(final_filtered_data)
    valid_rate_records = len(final_filtered_data[
        (final_filtered_data['Base Rate'].notna()) & 
        (final_filtered_data['Base Rate'] > 0)
    ])
    
    if 'Performance_Score' in final_filtered_data.columns:
        valid_perf_records = len(final_filtered_data[final_filtered_data['Performance_Score'].notna()])
        optimization_ready_records = len(final_filtered_data[
            (final_filtered_data['Base Rate'].notna()) & 
            (final_filtered_data['Base Rate'] > 0) & 
            (final_filtered_data['Performance_Score'].notna())
        ])
    else:
        valid_perf_records = 0
        optimization_ready_records = 0
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("📊 Total Records", f"{total_records:,}")
    
    with col2:
        rate_pct = (valid_rate_records / total_records * 100) if total_records > 0 else 0
        st.metric("💰 Valid Rates", f"{valid_rate_records:,}", f"{rate_pct:.1f}%")
    
    with col3:
        perf_pct = (valid_perf_records / total_records * 100) if total_records > 0 else 0
        st.metric("🎯 Valid Performance", f"{valid_perf_records:,}", f"{perf_pct:.1f}%")
    
    with col4:
        opt_pct = (optimization_ready_records / total_records * 100) if total_records > 0 else 0
        color = "normal" if opt_pct > 90 else "inverse" if opt_pct < 70 else "off"
        st.metric("🧮 Optimization Ready", f"{optimization_ready_records:,}", f"{opt_pct:.1f}%")
