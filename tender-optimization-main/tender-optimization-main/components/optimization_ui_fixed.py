"""
Unified Optimization UI components for the Carrier Tender Optimization Dashboard
Handles all user interface elements for linear programming optimization in one clean section
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header

def show_unified_optimization_interface(final_filtered_data):
    """Display unified optimization interface with all controls in one section"""
    
    # Initialize session state for optimization settings
    if 'opt_cost_weight' not in st.session_state:
        st.session_state.opt_cost_weight = 70
    if 'opt_performance_weight' not in st.session_state:
        st.session_state.opt_performance_weight = 30
    if 'carrier_constraints' not in st.session_state:
        st.session_state.carrier_constraints = {}
    if 'scac_constraints' not in st.session_state:
        st.session_state.scac_constraints = {}
    if 'category_constraints' not in st.session_state:
        st.session_state.category_constraints = {}
    if 'port_constraints' not in st.session_state:
        st.session_state.port_constraints = {}
    if 'optimization_results' not in st.session_state:
        st.session_state.optimization_results = None
    # We'll use the existing week filter from filters.py instead of creating a new one
    
    # Main optimization interface
    st.markdown("### 🎯 Optimization Control Center")
    
    # Create main layout with tabs for organized sections
    tab1, tab2, tab3, tab4 = st.tabs([
        "⚖️ Weights & Settings", 
        "🚛 Unified Constraints", 
        "🚀 Run Optimization",
        "📊 Results"
    ])
    
    with tab1:
        show_optimization_weights_section()
    
    with tab2:
        show_carrier_constraints_section(final_filtered_data)
    
    with tab3:
        show_optimization_execution_section(final_filtered_data)
    
    with tab4:
        show_optimization_results_section()

def show_optimization_weights_section():
    """Cost and Performance importance weights section"""
    st.markdown("#### 🎚️ Cost vs Performance Balance")
    st.markdown("*Set the importance of cost savings versus carrier performance*")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**Cost Importance**")
        cost_weight = st.slider(
            "Cost Priority (%)",
            min_value=0,
            max_value=100,
            value=st.session_state.opt_cost_weight,
            step=5,
            key="cost_slider",
            help="Higher values prioritize cost savings",
            on_change=update_weights_callback
        )
        st.caption(f"💰 Cost Weight: {cost_weight}%")
    
    with col2:
        st.markdown("**Performance Importance**")
        performance_weight = st.slider(
            "Performance Priority (%)",
            min_value=0,
            max_value=100,
            value=st.session_state.opt_performance_weight,
            step=5,
            key="performance_slider",
            help="Higher values prioritize carrier performance",
            on_change=update_weights_callback
        )
        st.caption(f"📈 Performance Weight: {performance_weight}%")
    
    # Auto-balance weights to sum to 100%
    total_weight = cost_weight + performance_weight
    if total_weight != 100:
        if total_weight > 0:
            normalized_cost = round((cost_weight / total_weight) * 100)
            normalized_perf = 100 - normalized_cost
            st.info(f"🔄 Weights normalized: Cost {normalized_cost}% | Performance {normalized_perf}%")
        else:
            st.warning("⚠️ Please set at least one weight above 0%")
    
    # Store normalized weights
    if total_weight > 0:
        st.session_state.normalized_cost_weight = cost_weight / total_weight
        st.session_state.normalized_performance_weight = performance_weight / total_weight
    
    # Visual balance indicator
    if total_weight > 0:
        st.markdown("**Balance Visualization**")
        progress_col1, progress_col2 = st.columns(2)
        with progress_col1:
            st.progress(cost_weight / 100, text="Cost Focus")
        with progress_col2:
            st.progress(performance_weight / 100, text="Performance Focus")

def update_weights_callback():
    """Callback to update weights in session state"""
    st.session_state.opt_cost_weight = st.session_state.cost_slider
    st.session_state.opt_performance_weight = st.session_state.performance_slider
    
    # Add normalized weights to session state (0.0-1.0 scale)
    st.session_state.normalized_cost_weight = st.session_state.cost_slider / 100.0
    st.session_state.normalized_performance_weight = st.session_state.performance_slider / 100.0

def show_carrier_constraints_section(final_filtered_data):
    """Completely unified constraints interface with all types in one view"""
    st.markdown("#### 🔗 Unified Constraints Dashboard")
    st.markdown("*Set constraints and allocations for carriers across ports and categories*")
    
    if len(final_filtered_data) == 0:
        st.warning("No data available for constraints")
        return
    
    # Get unique carriers - try both 'Carrier' and 'Dray SCAC(FL)' columns
    # Robust carrier extraction: prefer 'Carrier' then 'Dray SCAC(FL)'; coerce to str, drop NaN/empty
    carriers = []
    if final_filtered_data is None or final_filtered_data.empty:
        carriers = []
    else:
        carrier_series = None
        for col in ['Carrier', 'Dray SCAC(FL)']:
            if col in final_filtered_data.columns:
                s = final_filtered_data[col].dropna()
                if len(s) > 0:
                    carrier_series = s.astype(str).str.strip()
                    break
        if carrier_series is None:
            carriers = []
        else:
            carriers = sorted([c for c in pd.unique(carrier_series) if c and str(c).lower() != 'nan'])
        
    # Get unique SCACs
    scacs = []
    if 'Dray SCAC(FL)' in final_filtered_data.columns and not final_filtered_data['Dray SCAC(FL)'].isna().all():
        scacs = sorted(final_filtered_data['Dray SCAC(FL)'].unique())
        scacs = [scac for scac in scacs if pd.notna(scac)]  # Filter out NaN values
    
    # Get unique categories from the Category column
    categories = []
    if 'Category' in final_filtered_data.columns and not final_filtered_data['Category'].isna().all():
        categories = sorted(final_filtered_data['Category'].unique())
        categories = [category for category in categories if pd.notna(category)]  # Filter out NaN values
    # Found categories in data (no debug output)
        
    # Get unique ports if available
    ports = []
    if 'Discharged Port' in final_filtered_data.columns and not final_filtered_data['Discharged Port'].isna().all():
        ports = sorted(final_filtered_data['Discharged Port'].unique())
        ports = [port for port in ports if pd.notna(port)]  # Filter out NaN values
    
    # Initialize session state for constraints if not already present
    if 'scac_constraints' not in st.session_state:
        st.session_state.scac_constraints = {}
    
    if 'category_constraints' not in st.session_state:
        st.session_state.category_constraints = {}
        
    if 'port_constraints' not in st.session_state:
        st.session_state.port_constraints = {}
    
    # Show what's available for constraints
    constraint_options_available = []
    if carriers:
        constraint_options_available.append("Carrier")
    if scacs and scacs != carriers:  # Only add if different from carriers
        constraint_options_available.append("Carrier SCAC")
    if categories:
        constraint_options_available.append("Category")
    if ports:
        constraint_options_available.append("Port")
        
    if constraint_options_available:
        st.info(f"Constraint options available: {', '.join(constraint_options_available)}")
        
    if not carriers and not categories and not ports:
        st.warning("No constraint options found in data. Check that the necessary columns contain valid data.")
        return
    
    # Create a container to hold all constraints data for the unified table
    all_constraints = []
    
    # COMPLETELY UNIFIED CONSTRAINTS (Carriers, Ports, Categories)
    if carriers:
        st.subheader("🚚 Complete Unified Constraints")
        
        # Selections section - Create a row of multi-selects for all constraint types
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Create multi-select for carriers
            selected_carriers = st.multiselect(
                "Select carriers:",
                options=carriers,
                default=[carriers[0]] if carriers else [],  # Default to first carrier
                key="carrier_multiselect"
            )
        
        with col2:
            # Create multi-select for ports
            selected_ports = st.multiselect(
                "Select ports:",
                options=ports,
                default=[],
                key="unified_port_multiselect"
            )
            
        with col3:
            # Create multi-select for categories from the Category column
            selected_categories = st.multiselect(
                "Select categories:",
                options=categories,
                default=[],
                key="category_multiselect",
                help="Select one or more shipping categories to add constraints for"
            )
            
        # Create a container for all constraint data
        all_constraint_combinations = []
        
        # Process all selected carriers
        for carrier in selected_carriers:
            # Get carrier data for context
            if 'Carrier' in final_filtered_data.columns and carrier in final_filtered_data['Carrier'].values:
                carrier_data = final_filtered_data[final_filtered_data['Carrier'] == carrier]
            elif 'Dray SCAC(FL)' in final_filtered_data.columns:
                carrier_data = final_filtered_data[final_filtered_data['Dray SCAC(FL)'] == carrier]
            else:
                carrier_data = pd.DataFrame()
            
            # Check for the right container volume column
            if 'Total_Lane_Volume' in carrier_data.columns:
                volume_column = 'Total_Lane_Volume'
            elif 'Container Count' in carrier_data.columns:
                volume_column = 'Container Count'
            else:
                volume_column = None
            
            # Get carrier metrics
            total_volume = carrier_data[volume_column].sum() if (volume_column and len(carrier_data) > 0) else 0
            avg_rate = carrier_data['Base Rate'].mean() if ('Base Rate' in carrier_data.columns and len(carrier_data) > 0) else 0
            avg_performance = carrier_data['Performance_Score'].mean() if ('Performance_Score' in carrier_data.columns and len(carrier_data) > 0) else 0
            
            # Create a dedicated section for this carrier with port and category options
            st.markdown(f"### Carrier: {carrier}")
            st.markdown(f"**Total Volume: {int(total_volume)} containers | Avg Rate: ${avg_rate:.2f} | Avg Performance: {avg_performance:.2f}**")
            
            # Carrier-level constraints
            st.markdown("#### Overall Carrier Allocation")
            carrier_col1, carrier_col2 = st.columns(2)
            
            with carrier_col1:
                # Min containers input for carrier
                default_min = st.session_state.carrier_constraints.get(carrier, {}).get('min', 0)
                min_value = st.number_input(
                    "Minimum Containers for Carrier:",
                    min_value=0,
                    max_value=int(total_volume) if total_volume > 0 else 10000,
                    value=default_min,
                    step=10,
                    key=f"min_{carrier}_input"
                )
                # Update session state
                if carrier not in st.session_state.carrier_constraints:
                    st.session_state.carrier_constraints[carrier] = {}
                st.session_state.carrier_constraints[carrier]['min'] = min_value
                
            with carrier_col2:
                # Max containers input for carrier
                default_max = st.session_state.carrier_constraints.get(carrier, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
                max_value = st.number_input(
                    "Maximum Containers for Carrier:",
                    min_value=0,
                    max_value=int(total_volume * 1.5) if total_volume > 0 else 10000,  # Allow some flexibility
                    value=default_max,
                    step=10,
                    key=f"max_{carrier}_input"
                )
                # Update session state
                st.session_state.carrier_constraints[carrier]['max'] = max_value
            
            # Add carrier to constraints data
            all_constraints.append({
                'Type': 'Carrier',
                'Name': carrier,
                'Available Volume': int(total_volume),
                'Avg Rate': f"${avg_rate:.2f}",
                'Avg Performance': f"{avg_performance:.2f}",
                'Min': min_value,
                'Max': max_value
            })
            
            # PORT CONSTRAINTS FOR THIS CARRIER
            if selected_ports:
                st.markdown(f"#### 🚢 Port Constraints for {carrier}")
                
                for port in selected_ports:
                    # Filter data for this carrier and port
                    carrier_port_data = carrier_data[carrier_data['Discharged Port'] == port] if len(carrier_data) > 0 else pd.DataFrame()
                    
                    # Get volume for this carrier+port combination
                    port_volume = carrier_port_data[volume_column].sum() if (volume_column and len(carrier_port_data) > 0) else 0
                    
                    if port_volume > 0:
                        # Create a unique key for this carrier+port combination
                        combo_key = f"{carrier}_{port}"
                        
                        # Create a row for this port
                        st.markdown(f"**Port: {port} - Available: {int(port_volume)} containers**")
                        port_col1, port_col2 = st.columns(2)
                        
                        with port_col1:
                            # Min containers for this carrier+port
                            combo_min = st.number_input(
                                f"Min containers for {port}:",
                                min_value=0,
                                max_value=int(port_volume),
                                value=0,
                                step=5,
                                key=f"min_{combo_key}"
                            )
                            
                        with port_col2:
                            # Max containers for this carrier+port
                            combo_max = st.number_input(
                                f"Max containers for {port}:",
                                min_value=0,
                                max_value=int(port_volume * 1.5),
                                value=int(port_volume),
                                step=5,
                                key=f"max_{combo_key}"
                            )
                        
                        # Store this carrier+port constraint
                        if port not in st.session_state.port_constraints:
                            st.session_state.port_constraints[port] = {}
                        if carrier not in st.session_state.port_constraints[port]:
                            st.session_state.port_constraints[port][carrier] = {}
                        
                        st.session_state.port_constraints[port][carrier]['min'] = combo_min
                        st.session_state.port_constraints[port][carrier]['max'] = combo_max
                        
                        # Add to unified constraints
                        all_constraints.append({
                            'Type': 'Carrier+Port',
                            'Name': f"{carrier} @ {port}",
                            'Available Volume': int(port_volume),
                            'Min': combo_min,
                            'Max': combo_max
                        })
            
            # CATEGORY CONSTRAINTS FOR THIS CARRIER
            if selected_categories:
                st.markdown(f"#### 🏷️ Category Constraints for {carrier}")
                st.info(f"Set container allocation limits for each shipping category served by {carrier}")
                
                for category in selected_categories:
                    # Filter data for this carrier and category
                    carrier_category_data = carrier_data[carrier_data['Category'] == category] if len(carrier_data) > 0 else pd.DataFrame()
                    
                    # Get volume for this carrier+category combination
                    category_volume = carrier_category_data[volume_column].sum() if (volume_column and len(carrier_category_data) > 0) else 0
                    
                    if category_volume > 0:
                        # Create a unique key for this carrier+category combination
                        combo_key = f"{carrier}_{category}"
                        
                        # Create a row for this category
                        st.markdown(f"**Category: {category} - Available: {int(category_volume)} containers**")
                        cat_col1, cat_col2 = st.columns(2)
                        
                        with cat_col1:
                            # Min containers for this carrier+category
                            combo_min = st.number_input(
                                f"Min containers for {category}:",
                                min_value=0,
                                max_value=int(category_volume),
                                value=0,
                                step=5,
                                key=f"min_{combo_key}"
                            )
                            
                        with cat_col2:
                            # Max containers for this carrier+category
                            combo_max = st.number_input(
                                f"Max containers for {category}:",
                                min_value=0,
                                max_value=int(category_volume * 1.5),
                                value=int(category_volume),
                                step=5,
                                key=f"max_{combo_key}"
                            )
                        
                        # Store this carrier+category constraint
                        if category not in st.session_state.category_constraints:
                            st.session_state.category_constraints[category] = {}
                        if carrier not in st.session_state.category_constraints[category]:
                            st.session_state.category_constraints[category][carrier] = {}
                        
                        st.session_state.category_constraints[category][carrier]['min'] = combo_min
                        st.session_state.category_constraints[category][carrier]['max'] = combo_max
                        
                        # Add to unified constraints
                        all_constraints.append({
                            'Type': 'Carrier+Category',
                            'Name': f"{carrier} / {category}",
                            'Available Volume': int(category_volume),
                            'Min': combo_min,
                            'Max': combo_max
                        })
            
            st.markdown("---")
    
    # We're removing the standalone PORT CONSTRAINTS section and integrating it with carrier constraints
    
    # We're removing the standalone CATEGORY CONSTRAINTS section and integrating it with carrier constraints
    
    # UNIFIED CONSTRAINT TABLE
    if all_constraints:
        st.subheader("🔄 All Constraints in One View")
        st.markdown("*Edit all constraints in one place*")
        
        # Create a dataframe with all constraints
        constraints_df = pd.DataFrame(all_constraints)
        
        # Make the dataframe editable
        edited_df = st.data_editor(
            constraints_df,
            column_config={
                'Type': st.column_config.TextColumn('Type', disabled=True),
                'Name': st.column_config.TextColumn('Name', disabled=True),
                'Available Volume': st.column_config.NumberColumn('Available Volume', disabled=True, format="%d"),
                'Avg Rate': st.column_config.TextColumn('Avg Rate', disabled=True),
                'Avg Performance': st.column_config.TextColumn('Avg Performance', disabled=True),
                'Min': st.column_config.NumberColumn('Min Containers', min_value=0, step=10, format="%d"),
                'Max': st.column_config.NumberColumn('Max Containers', min_value=0, step=10, format="%d")
            },
            hide_index=True,
            use_container_width=True,
            key="unified_constraints_table"
        )
        
        # Update session state based on edited values
        for _, row in edited_df.iterrows():
            constraint_type = row['Type']
            constraint_name = row['Name']
            min_value = int(row['Min'])
            max_value = int(row['Max'])
            
            # Update the appropriate constraint type
            if constraint_type == 'Carrier':
                if constraint_name not in st.session_state.carrier_constraints:
                    st.session_state.carrier_constraints[constraint_name] = {}
                st.session_state.carrier_constraints[constraint_name]['min'] = min_value
                st.session_state.carrier_constraints[constraint_name]['max'] = max_value
            
            elif constraint_type == 'Port':
                if constraint_name not in st.session_state.port_constraints:
                    st.session_state.port_constraints[constraint_name] = {}
                st.session_state.port_constraints[constraint_name]['min'] = min_value
                st.session_state.port_constraints[constraint_name]['max'] = max_value
            
            elif constraint_type == 'Category':
                if constraint_name not in st.session_state.category_constraints:
                    st.session_state.category_constraints[constraint_name] = {}
                st.session_state.category_constraints[constraint_name]['min'] = min_value
                st.session_state.category_constraints[constraint_name]['max'] = max_value
            
            elif constraint_type == 'SCAC':
                if constraint_name not in st.session_state.scac_constraints:
                    st.session_state.scac_constraints[constraint_name] = {}
                st.session_state.scac_constraints[constraint_name]['min'] = min_value
                st.session_state.scac_constraints[constraint_name]['max'] = max_value
        
        # Run optimization button at the bottom of the constraints section
        st.markdown("---")
        
        col1, col2 = st.columns([3, 1])
        with col1:
            if st.button(
                "🚀 Run Optimization Analysis",
                type="primary",
                use_container_width=True,
                key="run_optimization_button"
            ):
                run_unified_optimization(final_filtered_data)
        
        with col2:
            if st.button("🔄 Reset", help="Clear all constraints", key="reset_constraints_button"):
                # Reset all constraints
                st.session_state.carrier_constraints = {}
                st.session_state.scac_constraints = {}
                st.session_state.category_constraints = {}
                st.session_state.port_constraints = {}
                st.session_state.optimization_results = None
                st.rerun()
    else:
        st.warning("No constraint options selected. Please select carriers, ports, or categories to add constraints.")

def show_optimization_execution_section(final_filtered_data):
    """Optimization execution and settings section"""
    st.markdown("#### 🚀 Run Optimization")
    
    # Pre-flight checks
    st.markdown("**Pre-flight Checks**")
    
    checks_passed = True
    
    # Check 1: Data availability
    if len(final_filtered_data) > 0:
        st.success(f"✅ Data: {len(final_filtered_data)} records available")
    else:
        st.error("❌ No data available for optimization")
        checks_passed = False
    
    # Check 2: Performance scores
    if 'Performance_Score' in final_filtered_data.columns:
        missing_perf = final_filtered_data['Performance_Score'].isna().sum()
        if missing_perf == 0:
            st.success("✅ Performance: All records have performance scores")
        else:
            st.warning(f"⚠️ Performance: {missing_perf} records missing performance scores")
    else:
        st.error("❌ Performance: No performance scores found")
        checks_passed = False
    
    # Check 3: Multiple carriers per lane
    if len(final_filtered_data) > 0 and 'Lane' in final_filtered_data.columns and 'Carrier' in final_filtered_data.columns:
        lane_carriers = final_filtered_data.groupby('Lane')['Carrier'].nunique()
        multi_carrier_lanes = (lane_carriers > 1).sum()
        if multi_carrier_lanes > 0:
            st.success(f"✅ Choices: {multi_carrier_lanes} lanes have multiple carrier options")
        else:
            st.warning("⚠️ Choices: No lanes have multiple carrier options")
    
    # Check 4: Weights set
    total_weight = st.session_state.opt_cost_weight + st.session_state.opt_performance_weight
    if total_weight > 0:
        st.success(f"✅ Weights: Cost {st.session_state.opt_cost_weight}% | Performance {st.session_state.opt_performance_weight}%")
    else:
        st.error("❌ Weights: Please set optimization weights")
        checks_passed = False
    
    # Optimization button
    st.markdown("---")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button(
            "🚀 Run Optimization Analysis",
            type="primary",
            disabled=not checks_passed,
            use_container_width=True
        ):
            run_unified_optimization(final_filtered_data)
    
    with col2:
        if st.button("🔄 Reset", help="Clear all results and constraints"):
            # Explicitly ensure all constraint types are reset
            st.session_state.carrier_constraints = {}
            st.session_state.scac_constraints = {}
            st.session_state.category_constraints = {}
            st.session_state.port_constraints = {}
            reset_optimization_state()
            st.rerun()

def show_optimization_results_section():
    """Display optimization results and analysis"""
    if 'optimization_results' not in st.session_state or st.session_state.optimization_results is None:
        st.info("💡 Run optimization to see detailed results here")
        return
    
    results = st.session_state.optimization_results
    
    # Debug information
    with st.expander("Debug Information", expanded=False):
        st.write("Results available:", results is not None)
        st.write("Keys in results:", list(results.keys()) if isinstance(results, dict) else "Not a dictionary")
        st.write("Success flag:", results.get('success', 'Not available'))
    
    if not results.get('success', False):
        st.error(f"❌ Optimization failed: {results.get('error', 'Unknown error')}")
        return
    
    st.success("✅ Optimization completed successfully!")
    
    # Key metrics
    st.markdown("#### 📊 Optimization Summary")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric(
            "Total Cost",
            f"${results['total_cost']:,.2f}",
            delta=f"{results.get('cost_change', 0):+.2f}" if 'cost_change' in results else None
        )
    
    with col2:
        st.metric(
            "Containers Allocated",
            f"{results['containers_allocated']:,}",
            delta=f"{results['allocation_rate']:.1f}% of total"
        )
    
    with col3:
        st.metric(
            "Avg Performance",
            f"{results['avg_performance']:.2f}",
            delta=f"{results.get('performance_change', 0):+.2f}" if 'performance_change' in results else None
        )
    
    # Detailed allocation breakdown
    st.markdown("#### 🚛 Carrier Allocation Breakdown")
    
    if 'allocation_df' in results and len(results['allocation_df']) > 0:
        # Format the allocation dataframe for display
        display_df = results['allocation_df'].copy()
        if 'Cost' in display_df.columns:
            display_df['Cost'] = display_df['Cost'].apply(lambda x: f"${x:,.2f}")
        if 'Performance' in display_df.columns:
            display_df['Performance'] = display_df['Performance'].apply(lambda x: f"{x:.2f}")
        
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )
        
        # Download button for results
        csv_data = results['allocation_df'].to_csv(index=False)
        st.download_button(
            label="📥 Download Results CSV",
            data=csv_data,
            file_name="optimization_results.csv",
            mime="text/csv"
        )
    else:
        st.warning("No allocation details available")

def run_unified_optimization(final_filtered_data):
    """Execute the unified optimization process"""
    with st.spinner("🔄 Running optimization analysis..."):
        
        try:
            # Get current weights
            cost_weight = st.session_state.get('normalized_cost_weight', 0.7)
            performance_weight = st.session_state.get('normalized_performance_weight', 0.3)
            
            # Use the already filtered data from the main filters
            opt_data = final_filtered_data.copy()
                
            # Check if we have data to work with
            if len(opt_data) == 0:
                st.error("No data available for optimization. Please check your filters.")
                return
            
            # Simple allocation algorithm based on combined score
            results = perform_unified_allocation(
                opt_data, 
                cost_weight, 
                performance_weight,
                st.session_state.carrier_constraints,
                st.session_state.get('scac_constraints', {}),
                st.session_state.get('category_constraints', {}),
                st.session_state.get('port_constraints', {})
            )
            
            # Store results
            st.session_state.optimization_results = results
            
            if results['success']:
                st.success(f"✅ Optimization complete! Total cost: ${results['total_cost']:,.2f}")
                st.balloons()  # Celebrate success!
            else:
                st.error(f"❌ Optimization failed: {results['error']}")
                
        except Exception as e:
            st.error(f"❌ Optimization error: {str(e)}")
            st.session_state.optimization_results = {
                'success': False,
                'error': str(e)
            }

def reset_optimization_state():
    """Reset all optimization-related session state"""
    if 'optimization_results' in st.session_state:
        st.session_state.optimization_results = None

# Copy the function from the original file
def perform_unified_allocation(data, cost_weight, performance_weight, carrier_constraints, scac_constraints=None, category_constraints=None, port_constraints=None):
    """Perform the unified allocation algorithm with carrier, SCAC, category, and port constraints"""
    
    try:
        if len(data) == 0:
            return {'success': False, 'error': 'No data provided'}
        
        # Initialize constraints if not provided
        if scac_constraints is None:
            scac_constraints = {}
        if category_constraints is None:
            category_constraints = {}
        if port_constraints is None:
            port_constraints = {}
        
        # Ensure required columns exist - accept either Carrier or Dray SCAC(FL)
        required_cols = [['Carrier', 'Dray SCAC(FL)'], 'Base Rate', 'Performance_Score']
        
        missing_cols = []
        for col in required_cols:
            if isinstance(col, list):
                # For carrier columns, need at least one of the options
                if not any(option in data.columns for option in col):
                    missing_cols.append(' or '.join(col))
            elif col not in data.columns:
                missing_cols.append(col)
        
        if missing_cols:
            return {'success': False, 'error': f'Missing columns: {missing_cols}'}
            
        # Make sure we have Total_Lane_Volume, or add it if needed
        if 'Total_Lane_Volume' not in data.columns:
            if 'Container Count' in data.columns:
                data['Total_Lane_Volume'] = data['Container Count']
                print("Using Container Count as Total_Lane_Volume")
            else:
                # Default to 1 per row if no volume information
                data['Total_Lane_Volume'] = 1
                print("No volume columns found, using default value of 1")
        
        # Debug what columns we have
        print(f"Data columns: {data.columns.tolist()}")
        print(f"Volume data: Total_Lane_Volume sum = {data['Total_Lane_Volume'].sum()}")
        
        # Calculate combined scores for ranking
        data = data.copy()
        
        # Cost normalization (inverse - lower cost = higher score)
        min_cost = data['Base Rate'].min()
        max_cost = data['Base Rate'].max()
        if max_cost > min_cost:
            data['cost_score'] = 1 - ((data['Base Rate'] - min_cost) / (max_cost - min_cost))
        else:
            data['cost_score'] = 1.0
        
        # Performance normalization
        min_perf = data['Performance_Score'].min()
        max_perf = data['Performance_Score'].max()
        if max_perf > min_perf:
            data['perf_score'] = (data['Performance_Score'] - min_perf) / (max_perf - min_perf)
        else:
            data['perf_score'] = 1.0
        
        # Combined score
        data['combined_score'] = (data['cost_score'] * cost_weight + 
                                data['perf_score'] * performance_weight)
        
        # Sort by combined score (best first)
        data_ranked = data.sort_values('combined_score', ascending=False)
        
        # Get total containers to allocate
        total_containers = data['Total_Lane_Volume'].sum() if 'Total_Lane_Volume' in data.columns else len(data)
        remaining_containers = total_containers
        
        # Apply SCAC, category, and port pre-allocation based on constraints
        # Pre-allocate minimum containers to SCACs with constraints
        scac_allocation = {}
        for scac, scac_constraint in scac_constraints.items():
            min_scac_containers = scac_constraint.get('min', 0)
            if min_scac_containers > 0:
                scac_allocation[scac] = min_scac_containers
                remaining_containers -= min_scac_containers
        
        # Pre-allocate minimum containers to categories with constraints
        category_allocation = {}
        for category, category_constraint in category_constraints.items():
            min_category_containers = category_constraint.get('min', 0)
            if min_category_containers > 0:
                category_allocation[category] = min_category_containers
                remaining_containers -= min_category_containers
                
        # Pre-allocate minimum containers to ports with constraints
        port_allocation = {}
        for port, port_constraint in port_constraints.items():
            min_port_containers = port_constraint.get('min', 0)
            if min_port_containers > 0:
                port_allocation[port] = min_port_containers
                remaining_containers -= min_port_containers
        
        # Allocation tracking
        allocation_results = []
        
        # Allocate to each carrier based on ranking and constraints
        # Determine which carrier column to use
        carrier_column = 'Carrier' if 'Carrier' in data_ranked.columns else 'Dray SCAC(FL)'
        
        if carrier_column not in data_ranked.columns:
            return {'success': False, 'error': 'No carrier column found in data'}
        
        for carrier in data_ranked[carrier_column].unique():
            if pd.isna(carrier):
                continue
                
            carrier_data = data_ranked[data_ranked[carrier_column] == carrier]
            
            # Get constraints for this carrier
            carrier_constraint = carrier_constraints.get(carrier, {})
            min_containers = carrier_constraint.get('min', 0)
            max_containers = carrier_constraint.get('max', total_containers)
            
            # Available capacity for this carrier
            carrier_volume = carrier_data['Total_Lane_Volume'].sum() if 'Total_Lane_Volume' in carrier_data.columns else len(carrier_data)
            
            # Calculate allocation - ensure we allocate at least the minimum
            allocated = min(carrier_volume, max_containers)
            allocated = max(allocated, min_containers)  # At least the minimum
            
            # Track allocation in results
            if allocated > 0:
                avg_performance = carrier_data['Performance_Score'].mean()
                avg_cost = carrier_data['Base Rate'].mean()
                total_cost = avg_cost * allocated
                
                allocation_results.append({
                    'Carrier': carrier,
                    'Containers': allocated,
                    'Allocation %': (allocated / total_containers) * 100 if total_containers > 0 else 0,
                    'Performance': avg_performance,
                    'Cost': total_cost
                })
                
                remaining_containers -= allocated
        
        # Create a DataFrame for the results
        if not allocation_results:
            return {'success': False, 'error': 'No valid carriers found for allocation'}
        
        allocation_df = pd.DataFrame(allocation_results)
        allocation_df = allocation_df.sort_values('Allocation %', ascending=False)
        
        # Calculate summary metrics
        total_allocated = allocation_df['Containers'].sum()
        total_cost = allocation_df['Cost'].sum()
        
        # Calculate weighted average performance
        weighted_performance = (allocation_df['Performance'] * allocation_df['Containers']).sum() / allocation_df['Containers'].sum() if allocation_df['Containers'].sum() > 0 else 0
        
        return {
            'success': True,
            'allocation_df': allocation_df,
            'total_cost': total_cost,
            'avg_performance': weighted_performance,
            'containers_allocated': int(total_allocated),
            'allocation_rate': (total_allocated / total_containers) * 100 if total_containers > 0 else 0
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}
