"""
Consolidated Optimization UI components for the Carrier Tender Optimization Dashboard
Handles all user interface elements for linear programming optimization with a unified constraints view
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
    tab1, tab2, tab3 = st.tabs([
        "⚖️ Weights & Settings", 
        "🔄 All Constraints", 
        "📊 Results"
    ])
    
    with tab1:
        show_optimization_weights_section()
    
    with tab2:
        show_unified_constraints_section(final_filtered_data)
    
    with tab3:
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
    
    # Pre-flight checks
    st.markdown("#### 🧪 Pre-flight Checks")
    st.info("✅ Set your cost vs performance weights above, then run optimization after setting constraints")

    # Note: We'll handle the actual optimization run button in the unified constraints section
    # since we need access to the final_filtered_data there
            # Explicitly ensure all constraint types are reset
            st.session_state.carrier_constraints = {}
            st.session_state.scac_constraints = {}
            st.session_state.category_constraints = {}
            st.session_state.port_constraints = {}
            reset_optimization_state()
            st.rerun()

def update_weights_callback():
    """Callback to update weights in session state"""
    st.session_state.opt_cost_weight = st.session_state.cost_slider
    st.session_state.opt_performance_weight = st.session_state.performance_slider
    
    # Add normalized weights to session state (0.0-1.0 scale)
    st.session_state.normalized_cost_weight = st.session_state.cost_slider / 100.0
    st.session_state.normalized_performance_weight = st.session_state.performance_slider / 100.0

def show_unified_constraints_section(final_filtered_data):
    """Unified constraints view showing all constraint types together"""
    st.markdown("#### 🔗 Unified Constraints Dashboard")
    st.markdown("*Set minimum and maximum container limits across carriers, categories and ports*")
    
    if len(final_filtered_data) == 0:
        st.warning("No data available for constraints")
        return
    
    # Initialize container to hold all constraint data for summary
    all_constraints = []
    
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
    
    # Initialize session state for constraints if not already present
    if 'carrier_constraints' not in st.session_state:
        st.session_state.carrier_constraints = {}
    
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
    
    if not carriers and not categories and not ports and not scacs:
        st.warning("No constraint options found in data. Check that the necessary columns contain valid data.")
        return
    
    # Unified constraints view - all constraint types in one table
    st.markdown("#### 📋 All Constraints")
    
    # CARRIER CONSTRAINTS SECTION
    if carriers:
        st.subheader("Carrier Constraints")
        
        # Create multi-select for carriers
        selected_carriers = st.multiselect(
            "Select carriers to add constraints for:",
            options=carriers,
            default=[carriers[0]] if carriers else []  # Default to first carrier
        )
        
        # Create a dataframe to display all carrier constraints
        carrier_constraints_data = []
        
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
            
            total_volume = carrier_data[volume_column].sum() if (volume_column and len(carrier_data) > 0) else 0
            avg_rate = carrier_data['Base Rate'].mean() if ('Base Rate' in carrier_data.columns and len(carrier_data) > 0) else 0
            avg_performance = carrier_data['Performance_Score'].mean() if ('Performance_Score' in carrier_data.columns and len(carrier_data) > 0) else 0
            
            # Add carrier to constraints data
            carrier_constraints_data.append({
                'Type': 'Carrier',
                'Name': carrier,
                'Available Volume': total_volume,
                'Avg Rate': f"${avg_rate:.2f}",
                'Avg Performance': f"{avg_performance:.2f}",
                'Min Containers': st.session_state.carrier_constraints.get(carrier, {}).get('min', 0),
                'Max Containers': st.session_state.carrier_constraints.get(carrier, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
            
            # Add to all constraints for summary
            all_constraints.append({
                'Type': 'Carrier',
                'Name': carrier,
                'Min': st.session_state.carrier_constraints.get(carrier, {}).get('min', 0),
                'Max': st.session_state.carrier_constraints.get(carrier, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
        
        # Create editable dataframe for carrier constraints
        if carrier_constraints_data:
            carrier_df = pd.DataFrame(carrier_constraints_data)
            
            edited_carrier_df = st.data_editor(
                carrier_df,
                column_config={
                    'Type': st.column_config.TextColumn('Type', disabled=True),
                    'Name': st.column_config.TextColumn('Name', disabled=True),
                    'Available Volume': st.column_config.NumberColumn('Available Volume', disabled=True),
                    'Avg Rate': st.column_config.TextColumn('Avg Rate', disabled=True),
                    'Avg Performance': st.column_config.TextColumn('Avg Performance', disabled=True),
                    'Min Containers': st.column_config.NumberColumn('Min Containers', min_value=0, step=10),
                    'Max Containers': st.column_config.NumberColumn('Max Containers', min_value=0, step=10)
                },
                use_container_width=True,
                hide_index=True,
                key="carrier_constraints_editor"
            )
            
            # Update session state with edited values
            for _, row in edited_carrier_df.iterrows():
                carrier_name = row['Name']
                min_containers = row['Min Containers']
                max_containers = row['Max Containers']
                
                if carrier_name not in st.session_state.carrier_constraints:
                    st.session_state.carrier_constraints[carrier_name] = {}
                
                st.session_state.carrier_constraints[carrier_name]['min'] = min_containers
                st.session_state.carrier_constraints[carrier_name]['max'] = max_containers
    
    # PORT CONSTRAINTS SECTION
    if ports:
        st.subheader("Port Constraints")
        
        # Create multi-select for ports
        selected_ports = st.multiselect(
            "Select ports to add constraints for:",
            options=ports,
            default=[]
        )
        
        # Create a dataframe to display all port constraints
        port_constraints_data = []
        
        for port in selected_ports:
            port_data = final_filtered_data[final_filtered_data['Discharged Port'] == port]
            
            # Check for the right container volume column
            if 'Total_Lane_Volume' in port_data.columns:
                volume_column = 'Total_Lane_Volume'
            elif 'Container Count' in port_data.columns:
                volume_column = 'Container Count'
            else:
                volume_column = None
            
            total_volume = port_data[volume_column].sum() if (volume_column and len(port_data) > 0) else 0
            
            # Add port to constraints data
            port_constraints_data.append({
                'Type': 'Port',
                'Name': port,
                'Available Volume': total_volume,
                'Min Containers': st.session_state.port_constraints.get(port, {}).get('min', 0),
                'Max Containers': st.session_state.port_constraints.get(port, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
            
            # Add to all constraints for summary
            all_constraints.append({
                'Type': 'Port',
                'Name': port,
                'Min': st.session_state.port_constraints.get(port, {}).get('min', 0),
                'Max': st.session_state.port_constraints.get(port, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
        
        # Create editable dataframe for port constraints
        if port_constraints_data:
            port_df = pd.DataFrame(port_constraints_data)
            
            edited_port_df = st.data_editor(
                port_df,
                column_config={
                    'Type': st.column_config.TextColumn('Type', disabled=True),
                    'Name': st.column_config.TextColumn('Name', disabled=True),
                    'Available Volume': st.column_config.NumberColumn('Available Volume', disabled=True),
                    'Min Containers': st.column_config.NumberColumn('Min Containers', min_value=0, step=10),
                    'Max Containers': st.column_config.NumberColumn('Max Containers', min_value=0, step=10)
                },
                use_container_width=True,
                hide_index=True,
                key="port_constraints_editor"
            )
            
            # Update session state with edited values
            for _, row in edited_port_df.iterrows():
                port_name = row['Name']
                min_containers = row['Min Containers']
                max_containers = row['Max Containers']
                
                if port_name not in st.session_state.port_constraints:
                    st.session_state.port_constraints[port_name] = {}
                
                st.session_state.port_constraints[port_name]['min'] = min_containers
                st.session_state.port_constraints[port_name]['max'] = max_containers
    
    # CATEGORY CONSTRAINTS SECTION
    if categories:
        st.subheader("Category Constraints")
        
        # Create multi-select for categories
        selected_categories = st.multiselect(
            "Select categories to add constraints for:",
            options=categories,
            default=[]
        )
        
        # Create a dataframe to display all category constraints
        category_constraints_data = []
        
        for category in selected_categories:
            category_data = final_filtered_data[final_filtered_data['Category'] == category]
            
            # Check for the right container volume column
            if 'Total_Lane_Volume' in category_data.columns:
                volume_column = 'Total_Lane_Volume'
            elif 'Container Count' in category_data.columns:
                volume_column = 'Container Count'
            else:
                volume_column = None
            
            total_volume = category_data[volume_column].sum() if (volume_column and len(category_data) > 0) else 0
            
            # Add category to constraints data
            category_constraints_data.append({
                'Type': 'Category',
                'Name': category,
                'Available Volume': total_volume,
                'Min Containers': st.session_state.category_constraints.get(category, {}).get('min', 0),
                'Max Containers': st.session_state.category_constraints.get(category, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
            
            # Add to all constraints for summary
            all_constraints.append({
                'Type': 'Category',
                'Name': category,
                'Min': st.session_state.category_constraints.get(category, {}).get('min', 0),
                'Max': st.session_state.category_constraints.get(category, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
        
        # Create editable dataframe for category constraints
        if category_constraints_data:
            category_df = pd.DataFrame(category_constraints_data)
            
            edited_category_df = st.data_editor(
                category_df,
                column_config={
                    'Type': st.column_config.TextColumn('Type', disabled=True),
                    'Name': st.column_config.TextColumn('Name', disabled=True),
                    'Available Volume': st.column_config.NumberColumn('Available Volume', disabled=True),
                    'Min Containers': st.column_config.NumberColumn('Min Containers', min_value=0, step=10),
                    'Max Containers': st.column_config.NumberColumn('Max Containers', min_value=0, step=10)
                },
                use_container_width=True,
                hide_index=True,
                key="category_constraints_editor"
            )
            
            # Update session state with edited values
            for _, row in edited_category_df.iterrows():
                category_name = row['Name']
                min_containers = row['Min Containers']
                max_containers = row['Max Containers']
                
                if category_name not in st.session_state.category_constraints:
                    st.session_state.category_constraints[category_name] = {}
                
                st.session_state.category_constraints[category_name]['min'] = min_containers
                st.session_state.category_constraints[category_name]['max'] = max_containers
    
    # SCAC CONSTRAINTS SECTION
    if scacs and not carriers: # Only show if different from carriers
        st.subheader("SCAC Constraints")
        
        # Create multi-select for SCACs
        selected_scacs = st.multiselect(
            "Select SCACs to add constraints for:",
            options=scacs,
            default=[]
        )
        
        # Create a dataframe to display all SCAC constraints
        scac_constraints_data = []
        
        for scac in selected_scacs:
            scac_data = final_filtered_data[final_filtered_data['Dray SCAC(FL)'] == scac]
            
            # Check for the right container volume column
            if 'Total_Lane_Volume' in scac_data.columns:
                volume_column = 'Total_Lane_Volume'
            elif 'Container Count' in scac_data.columns:
                volume_column = 'Container Count'
            else:
                volume_column = None
            
            total_volume = scac_data[volume_column].sum() if (volume_column and len(scac_data) > 0) else 0
            
            # Add SCAC to constraints data
            scac_constraints_data.append({
                'Type': 'SCAC',
                'Name': scac,
                'Available Volume': total_volume,
                'Min Containers': st.session_state.scac_constraints.get(scac, {}).get('min', 0),
                'Max Containers': st.session_state.scac_constraints.get(scac, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
            
            # Add to all constraints for summary
            all_constraints.append({
                'Type': 'SCAC',
                'Name': scac,
                'Min': st.session_state.scac_constraints.get(scac, {}).get('min', 0),
                'Max': st.session_state.scac_constraints.get(scac, {}).get('max', int(total_volume) if total_volume > 0 else 1000)
            })
        
        # Create editable dataframe for SCAC constraints
        if scac_constraints_data:
            scac_df = pd.DataFrame(scac_constraints_data)
            
            edited_scac_df = st.data_editor(
                scac_df,
                column_config={
                    'Type': st.column_config.TextColumn('Type', disabled=True),
                    'Name': st.column_config.TextColumn('Name', disabled=True),
                    'Available Volume': st.column_config.NumberColumn('Available Volume', disabled=True),
                    'Min Containers': st.column_config.NumberColumn('Min Containers', min_value=0, step=10),
                    'Max Containers': st.column_config.NumberColumn('Max Containers', min_value=0, step=10)
                },
                use_container_width=True,
                hide_index=True,
                key="scac_constraints_editor"
            )
            
            # Update session state with edited values
            for _, row in edited_scac_df.iterrows():
                scac_name = row['Name']
                min_containers = row['Min Containers']
                max_containers = row['Max Containers']
                
                if scac_name not in st.session_state.scac_constraints:
                    st.session_state.scac_constraints[scac_name] = {}
                
                st.session_state.scac_constraints[scac_name]['min'] = min_containers
                st.session_state.scac_constraints[scac_name]['max'] = max_containers
    
    # CONSTRAINT SUMMARY
    if all_constraints:
        st.subheader("Constraints Summary")
        summary_df = pd.DataFrame(all_constraints)
        
        st.dataframe(
            summary_df,
            column_config={
                'Type': st.column_config.TextColumn('Type'),
                'Name': st.column_config.TextColumn('Name'),
                'Min': st.column_config.NumberColumn('Min Containers'),
                'Max': st.column_config.NumberColumn('Max Containers')
            },
            use_container_width=True,
            hide_index=True
        )

def show_optimization_results_section():
    """Display optimization results and analysis"""
    if 'optimization_results' not in st.session_state or st.session_state.optimization_results is None:
        st.info("💡 Run optimization to see detailed results here")
        return
    
    results = st.session_state.optimization_results
    
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

def reset_optimization_state():
    """Reset all optimization-related session state"""
    if 'optimization_results' in st.session_state:
        st.session_state.optimization_results = None

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

# Copy the allocation function from the original file
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
