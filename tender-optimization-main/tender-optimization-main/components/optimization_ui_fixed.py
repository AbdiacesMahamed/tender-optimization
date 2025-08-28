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
    
    # Main optimization interface
    st.markdown("### 🎯 Optimization Control Center")
    
    # Create main layout with tabs for organized sections
    tab1, tab2, tab3, tab4 = st.tabs([
        "⚖️ Weights & Settings", 
        "🚛 Carrier Constraints", 
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
    """Unified constraints and limits section for carriers, SCACs, categories and ports"""
    st.markdown("#### 🚛 Unified Constraints Dashboard")
    st.markdown("*Set minimum and maximum container limits for carriers, categories and ports*")
    
    if len(final_filtered_data) == 0:
        st.warning("No data available for constraints")
        return
    
    # Get unique carriers - try both 'Carrier' and 'Dray SCAC(FL)' columns
    carriers = []
    if 'Carrier' in final_filtered_data.columns and not final_filtered_data['Carrier'].isna().all():
        carriers = sorted(final_filtered_data['Carrier'].unique())
    elif 'Dray SCAC(FL)' in final_filtered_data.columns and not final_filtered_data['Dray SCAC(FL)'].isna().all():
        carriers = sorted(final_filtered_data['Dray SCAC(FL)'].unique())
        
    carriers = [carrier for carrier in carriers if pd.notna(carrier)]  # Filter out NaN values
    
    # Get unique SCACs
    scacs = []
    if 'Dray SCAC(FL)' in final_filtered_data.columns and not final_filtered_data['Dray SCAC(FL)'].isna().all():
        scacs = sorted(final_filtered_data['Dray SCAC(FL)'].unique())
        scacs = [scac for scac in scacs if pd.notna(scac)]  # Filter out NaN values
    
    # Get unique categories if available
    categories = []
    if 'Category' in final_filtered_data.columns and not final_filtered_data['Category'].isna().all():
        categories = sorted(final_filtered_data['Category'].unique())
        categories = [category for category in categories if pd.notna(category)]  # Filter out NaN values
        
    # Get unique ports if available
    ports = []
    if 'Discharged Port' in final_filtered_data.columns and not final_filtered_data['Discharged Port'].isna().all():
        ports = sorted(final_filtered_data['Discharged Port'].unique())
        ports = [port for port in ports if pd.notna(port)]  # Filter out NaN values
    
    # Initialize session state for SCAC, Category, and Port constraints if not already present
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
    if scacs:
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
        
    # Create tabs for different constraint types
    constraint_tabs = []
    
    if carriers:
        constraint_tabs.append("🚚 Carriers")
    if scacs:
        constraint_tabs.append("📦 Carrier SCACs")
    if categories:
        constraint_tabs.append("🏷️ Categories")
    if ports:
        constraint_tabs.append("🚢 Ports")
    
    if constraint_tabs:
        tabs = st.tabs(constraint_tabs)
        
        # Track tab index for each constraint type
        tab_index = 0
        
        # Carrier constraints tab
        if carriers:
            with tabs[tab_index]:
                st.markdown("#### 🚚 Carrier Constraints")
                st.markdown("*Set minimum and maximum container limits per carrier*")
                
                # Create constraints for each carrier
                for i, carrier in enumerate(carriers):
                    with st.expander(f"🏢 {carrier} Constraints", expanded=i < 3):  # Expand first 3
                        
                        # Get carrier data for context - check both Carrier and Dray SCAC columns
                        if 'Carrier' in final_filtered_data.columns and carrier in final_filtered_data['Carrier'].values:
                            carrier_data = final_filtered_data[final_filtered_data['Carrier'] == carrier]
                        elif 'Dray SCAC(FL)' in final_filtered_data.columns:
                            carrier_data = final_filtered_data[final_filtered_data['Dray SCAC(FL)'] == carrier]
                        else:
                            carrier_data = pd.DataFrame()
                        
                        total_volume = carrier_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in carrier_data.columns and len(carrier_data) > 0) else 0
                        avg_rate = carrier_data['Base Rate'].mean() if ('Base Rate' in carrier_data.columns and len(carrier_data) > 0) else 0
                        avg_performance = carrier_data['Performance_Score'].mean() if ('Performance_Score' in carrier_data.columns and len(carrier_data) > 0) else 0
                        
                        # Context metrics
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Available Volume", f"{total_volume:,.0f}")
                        with col2:
                            st.metric("Avg Rate", f"${avg_rate:,.2f}")
                        with col3:
                            st.metric("Avg Performance", f"{avg_performance:.2f}")
                        
                        # Constraint inputs
                        constraint_col1, constraint_col2 = st.columns(2)
                        
                        # Convert carrier to string and replace spaces
                        carrier_str = str(carrier).replace(' ', '_')
                        carrier_key = f"tabbed_carrier_{carrier_str}"
                        
                        with constraint_col1:
                            min_containers = st.number_input(
                                "Minimum Containers",
                                min_value=0,
                                max_value=int(total_volume) if total_volume > 0 else 1000,
                                value=st.session_state.carrier_constraints.get(carrier, {}).get('min', 0),
                                step=10,
                                key=f"{carrier_key}_min",
                                help="Minimum containers this carrier must handle"
                            )
                        
                        with constraint_col2:
                            max_containers = st.number_input(
                                "Maximum Containers",
                                min_value=min_containers,
                                max_value=int(total_volume * 2) if total_volume > 0 else 2000,  # Allow over-allocation
                                value=st.session_state.carrier_constraints.get(carrier, {}).get('max', int(total_volume) if total_volume > 0 else 1000),
                                step=10,
                                key=f"{carrier_key}_max",
                                help="Maximum containers this carrier can handle"
                            )
                        
                        # Update constraints in session state
                        if carrier not in st.session_state.carrier_constraints:
                            st.session_state.carrier_constraints[carrier] = {}
                        
                        st.session_state.carrier_constraints[carrier]['min'] = min_containers
                        st.session_state.carrier_constraints[carrier]['max'] = max_containers
            
            tab_index += 1
        
        # SCAC constraints tab
        if scacs:
            with tabs[tab_index]:
                st.markdown("#### 📦 Carrier SCAC Constraints")
                st.markdown("*Set minimum and maximum container limits per Carrier SCAC*")
                
                # Create a multi-select for Carrier SCACs to add constraints to
                selected_scacs = st.multiselect(
                    "Select Carrier SCACs to add constraints for:",
                    options=scacs,
                    default=[]
                )
                
                for scac in selected_scacs:
                    scac_data = final_filtered_data[final_filtered_data['Dray SCAC(FL)'] == scac]
                    total_volume = scac_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in scac_data.columns and len(scac_data) > 0) else 0
                    
                    # Format SCAC for key
                    scac_str = str(scac).replace(' ', '_')
                    scac_key = f"tabbed_scac_{scac_str}"
                    
                    with st.expander(f"📦 Carrier {scac} Constraints", expanded=True):
                        scac_col1, scac_col2 = st.columns(2)
                        
                        with scac_col1:
                            scac_min = st.number_input(
                                "Minimum Containers",
                                min_value=0,
                                max_value=int(total_volume) if total_volume > 0 else 1000,
                                value=st.session_state.scac_constraints.get(scac, {}).get('min', 0),
                                step=10,
                                key=f"{scac_key}_min",
                                help="Minimum containers this Carrier must handle"
                            )
                        
                        with scac_col2:
                            scac_max = st.number_input(
                                "Maximum Containers",
                                min_value=scac_min,
                                max_value=int(total_volume * 2) if total_volume > 0 else 2000,  # Allow over-allocation
                                value=st.session_state.scac_constraints.get(scac, {}).get('max', int(total_volume) if total_volume > 0 else 1000),
                                step=10,
                                key=f"{scac_key}_max",
                                help="Maximum containers this Carrier can handle"
                            )
                        
                        # Update constraints in session state
                        if scac not in st.session_state.scac_constraints:
                            st.session_state.scac_constraints[scac] = {}
                        
                        st.session_state.scac_constraints[scac]['min'] = scac_min
                        st.session_state.scac_constraints[scac]['max'] = scac_max
            
            tab_index += 1
        
        # Category constraints tab
        if categories:
            with tabs[tab_index]:
                st.markdown("#### 🏷️ Category Constraints")
                st.markdown("*Set minimum and maximum container limits per category*")
                
                # Create a multi-select for categories to add constraints to
                selected_categories = st.multiselect(
                    "Select categories to add constraints for:",
                    options=categories,
                    default=[]
                )
                
                for category in selected_categories:
                    category_data = final_filtered_data[final_filtered_data['Category'] == category]
                    total_volume = category_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in category_data.columns and len(category_data) > 0) else 0
                    
                    # Format category for key
                    category_str = str(category).replace(' ', '_')
                    category_key = f"tabbed_category_{category_str}"
                    
                    with st.expander(f"🏷️ {category} Constraints", expanded=True):
                        category_col1, category_col2 = st.columns(2)
                        
                        with category_col1:
                            category_min = st.number_input(
                                "Minimum Containers",
                                min_value=0,
                                max_value=int(total_volume) if total_volume > 0 else 1000,
                                value=st.session_state.category_constraints.get(category, {}).get('min', 0),
                                step=10,
                                key=f"{category_key}_min",
                                help="Minimum containers for this category"
                            )
                        
                        with category_col2:
                            category_max = st.number_input(
                                "Maximum Containers",
                                min_value=category_min,
                                max_value=int(total_volume * 2) if total_volume > 0 else 2000,  # Allow over-allocation
                                value=st.session_state.category_constraints.get(category, {}).get('max', int(total_volume) if total_volume > 0 else 1000),
                                step=10,
                                key=f"{category_key}_max",
                                help="Maximum containers for this category"
                            )
                        
                        # Update constraints in session state
                        if category not in st.session_state.category_constraints:
                            st.session_state.category_constraints[category] = {}
                        
                        st.session_state.category_constraints[category]['min'] = category_min
                        st.session_state.category_constraints[category]['max'] = category_max
            
            tab_index += 1
        
        # Port constraints tab
        if ports:
            with tabs[tab_index]:
                st.markdown("#### 🚢 Port Constraints")
                st.markdown("*Set minimum and maximum container limits per port*")
                
                # Create a multi-select for ports to add constraints to
                selected_ports = st.multiselect(
                    "Select ports to add constraints for:",
                    options=ports,
                    default=[]
                )
                
                for port in selected_ports:
                    port_data = final_filtered_data[final_filtered_data['Discharged Port'] == port]
                    total_volume = port_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in port_data.columns and len(port_data) > 0) else 0
                    
                    # Format port for key
                    port_str = str(port).replace(' ', '_')
                    port_key = f"tabbed_port_{port_str}"
                    
                    with st.expander(f"🚢 Port {port} Constraints", expanded=True):
                        port_col1, port_col2 = st.columns(2)
                        
                        with port_col1:
                            port_min = st.number_input(
                                "Minimum Containers",
                                min_value=0,
                                max_value=int(total_volume) if total_volume > 0 else 1000,
                                value=st.session_state.port_constraints.get(port, {}).get('min', 0),
                                step=10,
                                key=f"{port_key}_min",
                                help="Minimum containers for this port"
                            )
                        
                        with port_col2:
                            port_max = st.number_input(
                                "Maximum Containers",
                                min_value=port_min,
                                max_value=int(total_volume * 2) if total_volume > 0 else 2000,  # Allow over-allocation
                                value=st.session_state.port_constraints.get(port, {}).get('max', int(total_volume) if total_volume > 0 else 1000),
                                step=10,
                                key=f"{port_key}_max",
                                help="Maximum containers for this port"
                            )
                        
                        # Update constraints in session state
                        if port not in st.session_state.port_constraints:
                            st.session_state.port_constraints[port] = {}
                        
                        st.session_state.port_constraints[port]['min'] = port_min
                        st.session_state.port_constraints[port]['max'] = port_max
    else:
        st.warning("No constraint options available. Please check the data structure.")

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
            
            # Prepare data
            opt_data = final_filtered_data.copy()
            
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
            else:
                # Default to 1 per row if no volume information
                data['Total_Lane_Volume'] = 1
        
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
