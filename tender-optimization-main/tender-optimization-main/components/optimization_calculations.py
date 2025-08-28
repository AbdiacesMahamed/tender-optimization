"""
Optimization calculation engine for the Carrier Tender Optimization Dashboard
Handles all linear programming calculations and optimization logic
"""
import streamlit as st
import pandas as pd
import numpy as np
from pulp import LpProblem, LpMinimize, LpMaximize, LpVariable, lpSum, LpStatus, value, PULP_CBC_CMD

def perform_optimization(opt_data, cost_weight, performance_weight, container_constraints=None, type_restrictions=None):
    """Perform the actual linear programming optimization with whole lane assignments and constraints"""
    
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
    add_optimization_constraints(prob, lane_week_carriers, container_constraints, type_restrictions, opt_data)
    
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

def add_optimization_constraints(prob, lane_week_carriers, container_constraints=None, type_restrictions=None, opt_data=None):
    """Add constraints for whole lane assignments with advanced constraints"""
    # Basic constraints: exactly one carrier per lane-week combination gets ALL the volume
    for (lane, week), group in lane_week_carriers.groupby(['Lane', 'Week Number']):
        if len(group) > 1:  # Only add constraint if there are multiple carrier options
            prob += lpSum([row['choice_var'] for _, row in group.iterrows()]) == 1
        else:
            # If only one carrier option, force it to be selected
            prob += group.iloc[0]['choice_var'] == 1
    
    # Add container count constraints if provided
    if container_constraints and opt_data is not None:
        add_container_count_constraints(prob, lane_week_carriers, container_constraints)
    
    # Add container type restrictions if provided
    if type_restrictions and opt_data is not None:
        add_container_type_constraints(prob, lane_week_carriers, type_restrictions, opt_data)

def add_container_count_constraints(prob, lane_week_carriers, container_constraints):
    """Add container count min/max constraints to the optimization problem"""
    
    # Group by port and carrier to apply constraints
    for constraint_key, constraint in container_constraints.items():
        port = constraint['port']
        carrier = constraint['carrier']
        min_count = constraint['min']
        max_count = constraint['max']
        
        # Find all lane-week combinations for this port-carrier pair
        matching_rows = lane_week_carriers[
            (lane_week_carriers['Discharged Port'] == port) & 
            (lane_week_carriers['Dray SCAC(FL)'] == carrier)
        ]
        
        if len(matching_rows) == 0:
            continue
        
        # Sum of selected volumes for this carrier at this port
        total_volume_expr = lpSum([
            row['choice_var'] * row['Total_Lane_Volume'] 
            for idx, row in matching_rows.iterrows()
        ])
        
        # Add minimum constraint
        if min_count > 0:
            prob += total_volume_expr >= min_count
        
        # Add maximum constraint
        if max_count is not None and max_count > 0:
            prob += total_volume_expr <= max_count

def add_container_type_constraints(prob, lane_week_carriers, type_restrictions, opt_data):
    """Add container type restrictions to the optimization problem"""
    
    # Check if category column exists
    category_column = None
    if 'Category' in opt_data.columns:
        category_column = 'Category'
    else:
        category_columns = [col for col in opt_data.columns if 'category' in col.lower() or 'type' in col.lower()]
        if category_columns:
            category_column = category_columns[0]
    
    if category_column is None:
        return  # Skip if no category column found
    
    # Apply type restrictions
    for restriction_key, restriction in type_restrictions.items():
        port = restriction['port']
        carrier = restriction['carrier']
        allowed_types = restriction['allowed_types']
        
        # Find lane-week combinations that have restricted container types
        for idx, row in lane_week_carriers.iterrows():
            if (row['Discharged Port'] == port and 
                row['Dray SCAC(FL)'] == carrier):
                
                # Check if this lane-week has any containers of restricted types
                lane_week_data = opt_data[
                    (opt_data['Lane'] == row['Lane']) & 
                    (opt_data['Week Number'] == row['Week Number']) &
                    (opt_data['Discharged Port'] == port)
                ]
                
                if len(lane_week_data) > 0:
                    # Get container types for this lane-week
                    lane_types = set(lane_week_data[category_column].dropna().unique())
                    
                    # If this lane has any container types not in allowed_types, restrict it
                    if not lane_types.issubset(set(allowed_types)):
                        # This carrier cannot handle this lane due to type restrictions
                        prob += row['choice_var'] == 0

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

def get_optimization_results(final_filtered_data, cost_weight=None, performance_weight=None, container_constraints=None, type_restrictions=None):
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
    
    # Get constraints from session state if not provided
    if container_constraints is None:
        container_constraints = st.session_state.get('container_constraints', {})
    if type_restrictions is None:
        type_restrictions = st.session_state.get('type_restrictions', {})
    
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
            add_optimization_constraints(prob, lane_week_carriers, container_constraints, type_restrictions, opt_data)
            
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
                            'Base Rate': row['Base Rate'],
                            'Performance_Score': row['Performance_Score'],
                            'Container Count': row['Total_Lane_Volume'],
                            'Total Rate': total_cost_for_lane
                        })
            else:
                return None  # Optimization failed
                
        except Exception as e:
            return None  # Error in optimization
    
    # Handle single-carrier lanes (no optimization needed)
    if len(single_carrier_lanes) > 0:
        single_carrier_data = opt_data[opt_data.set_index(['Lane', 'Week Number']).index.isin(single_carrier_lanes.index)]
        
        # Aggregate single-carrier data by Lane-Week-SCAC
        single_carrier_summary = single_carrier_data.groupby(['Lane', 'Week Number', 'Dray SCAC(FL)']).agg({
            'Base Rate': 'first',
            'Performance_Score': 'first',
            'Container Count': 'sum',
            'Discharged Port': 'first',
            'Facility': 'first'
        }).reset_index()
        
        for idx, row in single_carrier_summary.iterrows():
            total_cost_for_lane = row['Base Rate'] * row['Container Count']
            
            selected_assignments.append({
                'Discharged Port': row['Discharged Port'],
                'Lane': row['Lane'],
                'Week Number': row['Week Number'],
                'Facility': row['Facility'],
                'Dray SCAC(FL)': row['Dray SCAC(FL)'],
                'Base Rate': row['Base Rate'],
                'Performance_Score': row['Performance_Score'],
                'Container Count': row['Container Count'],
                'Total Rate': total_cost_for_lane
            })
    
    if len(selected_assignments) > 0:
        return pd.DataFrame(selected_assignments)
    else:
        return None
