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
    
    # Create a tabbed interface for cleaner organization
    tab1, tab2, tab3 = st.tabs(["⚙️ Settings", "🔒 Constraints", "📊 Results"])
    
    # Tab 1: Optimization Settings
    with tab1:
        show_optimization_settings()
    
    # Tab 2: Constraints Management
    with tab2:
        show_integrated_constraints_section(final_filtered_data)
    
    # Tab 3: Results Display
    with tab3:
        show_optimization_results_section(final_filtered_data)


def show_optimization_settings():
    """Display cost vs performance weighting sliders"""
    
    st.markdown("#### Optimization Weighting")
    
    # Two-column layout for slider and description
    col1, col2 = st.columns([2, 1])
    
    # Slider column
    with col1:
        cost_weight = st.slider(
            "Cost vs. Performance Balance", 
            min_value=0, 
            max_value=100, 
            value=st.session_state.opt_cost_weight,
            help="Slide left to prioritize performance, right to prioritize cost savings"
        )
        
        # Update both weights to always total 100%
        st.session_state.opt_cost_weight = cost_weight
        st.session_state.opt_performance_weight = 100 - cost_weight
    
    # Description column
    with col2:
        st.markdown(f"""
        **Current Weights:**
        - Cost: **{st.session_state.opt_cost_weight}%**
        - Performance: **{st.session_state.opt_performance_weight}%**
        """)
    
    st.markdown("---")
    st.markdown("""
    #### How the Optimization Works
    
    The carrier allocation model balances two key factors:
    1. **Rate Competitiveness**: Lower costs improve the score
    2. **Performance Quality**: Higher ratings improve the score
    
    Adjust the slider to find your optimal balance between savings and service quality.
    """)


def show_integrated_constraints_section(final_filtered_data):
    """Display an integrated view of all constraint types (carrier, category, port)"""
    
    st.markdown("#### Carrier and Lane Constraints")
    st.markdown("Set minimum and maximum volume percentages for carriers, categories, and ports.")
    
    # Extract all unique carriers, categories, and ports from the dataset
    carriers, scacs, categories, ports = extract_constraint_options(final_filtered_data)
    
    # Create tabs for different constraint types
    constraint_tab1, constraint_tab2, constraint_tab3, constraint_tab4 = st.tabs([
        "Carrier Name Constraints", 
        "Carrier SCAC Constraints",
        "Category Constraints",
        "Port Constraints"
    ])
    
    # Tab 1: Carrier Name Constraints
    with constraint_tab1:
        show_carrier_constraints(carriers)
        
    # Tab 2: Carrier SCAC Constraints
    with constraint_tab2:
        show_scac_constraints(scacs)
        
    # Tab 3: Category Constraints
    with constraint_tab3:
        show_category_constraints(categories)
        
    # Tab 4: Port Constraints
    with constraint_tab4:
        show_port_constraints(ports)


def extract_constraint_options(final_filtered_data):
    """Extract unique values for carriers, SCACs, categories and ports"""
    
    if final_filtered_data is None or final_filtered_data.empty:
        return [], [], [], []
    
    # Extract carriers from either Carrier or Dray SCAC column
    carriers = []
    if 'Carrier' in final_filtered_data.columns:
        carriers = sorted(final_filtered_data['Carrier'].dropna().unique().tolist())
    
    # Extract SCACs
    scacs = []
    for scac_col in ['Dray SCAC(FL)', 'SCAC', 'Carrier SCAC']:
        if scac_col in final_filtered_data.columns:
            scacs.extend(final_filtered_data[scac_col].dropna().unique().tolist())
    scacs = sorted(list(set(scacs)))
    
    # Extract categories
    categories = []
    for cat_col in ['Category', 'Lane Category', 'Service Category']:
        if cat_col in final_filtered_data.columns:
            categories.extend(final_filtered_data[cat_col].dropna().unique().tolist())
    categories = sorted(list(set(categories)))
    
    # Extract ports
    ports = []
    for port_col in ['Origin Port', 'Destination Port', 'Port', 'Origin', 'Destination']:
        if port_col in final_filtered_data.columns:
            ports.extend(final_filtered_data[port_col].dropna().unique().tolist())
    ports = sorted(list(set(ports)))
    
    return carriers, scacs, categories, ports


def show_carrier_constraints(carriers):
    """Display interface for setting carrier constraints by name"""
    
    if not carriers:
        st.warning("No carrier data available in the filtered dataset")
        return
    
    st.markdown("Set minimum and maximum allocation percentages for each carrier")
    st.markdown("Leave fields blank for unconstrained allocation")
    
    # Use a dataframe editor for a clean interface
    carrier_constraints_data = []
    
    for carrier in carriers:
        min_val = ""
        max_val = ""
        
        # Use existing constraints if available
        if carrier in st.session_state.carrier_constraints:
            constraints = st.session_state.carrier_constraints[carrier]
            min_val = constraints.get('min', "")
            max_val = constraints.get('max', "")
            
        carrier_constraints_data.append({
            "Carrier": carrier,
            "Min %": min_val,
            "Max %": max_val
        })
    
    # Convert to DataFrame for the editor
    df_carrier_constraints = pd.DataFrame(carrier_constraints_data)
    
    # Create an editable dataframe
    edited_df = st.data_editor(
        df_carrier_constraints,
        key="carrier_constraint_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed"
    )
    
    # Update session state with edited values
    for _, row in edited_df.iterrows():
        carrier = row['Carrier']
        min_val = row['Min %']
        max_val = row['Max %']
        
        if pd.notna(min_val) or pd.notna(max_val):
            # Convert to float or None
            min_percent = float(min_val) if pd.notna(min_val) and min_val != "" else None
            max_percent = float(max_val) if pd.notna(max_val) and max_val != "" else None
            
            # Store in session state
            st.session_state.carrier_constraints[carrier] = {
                'min': min_percent,
                'max': max_percent
            }
        elif carrier in st.session_state.carrier_constraints:
            # Remove empty constraints
            del st.session_state.carrier_constraints[carrier]


def show_scac_constraints(scacs):
    """Display interface for setting carrier SCAC constraints"""
    
    if not scacs:
        st.warning("No SCAC data available in the filtered dataset")
        return
    
    st.markdown("Set minimum and maximum allocation percentages for each carrier SCAC")
    st.markdown("Leave fields blank for unconstrained allocation")
    
    # Use a dataframe editor for a clean interface
    scac_constraints_data = []
    
    for scac in scacs:
        min_val = ""
        max_val = ""
        
        # Use existing constraints if available
        if scac in st.session_state.scac_constraints:
            constraints = st.session_state.scac_constraints[scac]
            min_val = constraints.get('min', "")
            max_val = constraints.get('max', "")
            
        scac_constraints_data.append({
            "SCAC": scac,
            "Min %": min_val,
            "Max %": max_val
        })
    
    # Convert to DataFrame for the editor
    df_scac_constraints = pd.DataFrame(scac_constraints_data)
    
    # Create an editable dataframe
    edited_df = st.data_editor(
        df_scac_constraints,
        key="scac_constraint_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed"
    )
    
    # Update session state with edited values
    for _, row in edited_df.iterrows():
        scac = row['SCAC']
        min_val = row['Min %']
        max_val = row['Max %']
        
        if pd.notna(min_val) or pd.notna(max_val):
            # Convert to float or None
            min_percent = float(min_val) if pd.notna(min_val) and min_val != "" else None
            max_percent = float(max_val) if pd.notna(max_val) and max_val != "" else None
            
            # Store in session state
            st.session_state.scac_constraints[scac] = {
                'min': min_percent,
                'max': max_percent
            }
        elif scac in st.session_state.scac_constraints:
            # Remove empty constraints
            del st.session_state.scac_constraints[scac]


def show_category_constraints(categories):
    """Display interface for setting category constraints"""
    
    if not categories:
        st.warning("No category data available in the filtered dataset")
        return
    
    st.markdown("Set minimum and maximum allocation percentages for each category")
    st.markdown("Leave fields blank for unconstrained allocation")
    
    # Initialize category constraints in session state if not exists
    if 'category_constraints' not in st.session_state:
        st.session_state.category_constraints = {}
    
    # Use a dataframe editor for a clean interface
    category_constraints_data = []
    
    for category in categories:
        min_val = ""
        max_val = ""
        
        # Use existing constraints if available
        if category in st.session_state.category_constraints:
            constraints = st.session_state.category_constraints[category]
            min_val = constraints.get('min', "")
            max_val = constraints.get('max', "")
            
        category_constraints_data.append({
            "Category": category,
            "Min %": min_val,
            "Max %": max_val
        })
    
    # Convert to DataFrame for the editor
    df_category_constraints = pd.DataFrame(category_constraints_data)
    
    # Create an editable dataframe
    edited_df = st.data_editor(
        df_category_constraints,
        key="category_constraint_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed"
    )
    
    # Update session state with edited values
    for _, row in edited_df.iterrows():
        category = row['Category']
        min_val = row['Min %']
        max_val = row['Max %']
        
        if pd.notna(min_val) or pd.notna(max_val):
            # Convert to float or None
            min_percent = float(min_val) if pd.notna(min_val) and min_val != "" else None
            max_percent = float(max_val) if pd.notna(max_val) and max_val != "" else None
            
            # Store in session state
            st.session_state.category_constraints[category] = {
                'min': min_percent,
                'max': max_percent
            }
        elif category in st.session_state.category_constraints:
            # Remove empty constraints
            del st.session_state.category_constraints[category]


def show_port_constraints(ports):
    """Display interface for setting port constraints"""
    
    if not ports:
        st.warning("No port data available in the filtered dataset")
        return
    
    st.markdown("Set minimum and maximum allocation percentages for each port")
    st.markdown("Leave fields blank for unconstrained allocation")
    
    # Initialize port constraints in session state if not exists
    if 'port_constraints' not in st.session_state:
        st.session_state.port_constraints = {}
    
    # Use a dataframe editor for a clean interface
    port_constraints_data = []
    
    for port in ports:
        min_val = ""
        max_val = ""
        
        # Use existing constraints if available
        if port in st.session_state.port_constraints:
            constraints = st.session_state.port_constraints[port]
            min_val = constraints.get('min', "")
            max_val = constraints.get('max', "")
            
        port_constraints_data.append({
            "Port": port,
            "Min %": min_val,
            "Max %": max_val
        })
    
    # Convert to DataFrame for the editor
    df_port_constraints = pd.DataFrame(port_constraints_data)
    
    # Create an editable dataframe
    edited_df = st.data_editor(
        df_port_constraints,
        key="port_constraint_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed"
    )
    
    # Update session state with edited values
    for _, row in edited_df.iterrows():
        port = row['Port']
        min_val = row['Min %']
        max_val = row['Max %']
        
        if pd.notna(min_val) or pd.notna(max_val):
            # Convert to float or None
            min_percent = float(min_val) if pd.notna(min_val) and min_val != "" else None
            max_percent = float(max_val) if pd.notna(max_val) and max_val != "" else None
            
            # Store in session state
            st.session_state.port_constraints[port] = {
                'min': min_percent,
                'max': max_percent
            }
        elif port in st.session_state.port_constraints:
            # Remove empty constraints
            del st.session_state.port_constraints[port]


def show_optimization_results_section(final_filtered_data):
    """Display the optimization results and trigger button"""
    
    st.markdown("#### Optimization Results")
    
    # Show the optimization button
    optimize_col1, optimize_col2 = st.columns([1, 2])
    
    with optimize_col1:
        st.button(
            "Run Optimization", 
            key="run_optimization_button",
            use_container_width=True,
            type="primary"
        )
    
    with optimize_col2:
        st.markdown("""
        Click to run the optimization with current settings and constraints.
        Results will appear below when processing is complete.
        """)
    
    # Show results if available
    if st.session_state.optimization_results is not None:
        display_optimization_results(final_filtered_data)
    else:
        st.info("No optimization results yet. Click 'Run Optimization' to generate results.")


def display_optimization_results(final_filtered_data):
    """Display optimization results in an informative format"""
    
    # Get results from session state
    results = st.session_state.optimization_results
    
    # Display summary metrics
    st.markdown("### Optimization Results Summary")
    
    metric_col1, metric_col2, metric_col3 = st.columns(3)
    
    with metric_col1:
        st.metric(
            label="Optimized Cost", 
            value=f"${results.get('optimized_cost', 0):,.2f}",
            delta=f"-${results.get('cost_savings', 0):,.2f}"
        )
    
    with metric_col2:
        st.metric(
            label="Average Performance Score", 
            value=f"{results.get('avg_performance', 0):.2f}",
            delta=f"{results.get('performance_change', 0):+.2f}"
        )
    
    with metric_col3:
        st.metric(
            label="Total Volume Allocated", 
            value=f"{results.get('total_volume', 0):,.0f}"
        )
    
    # Display allocation results table
    st.markdown("#### Carrier Allocation Results")
    
    allocation_df = results.get('allocation_df', pd.DataFrame())
    
    if not allocation_df.empty:
        # Format the dataframe for display
        display_df = allocation_df.copy()
        
        # Ensure percentage formatting
        if 'Allocation %' in display_df.columns:
            display_df['Allocation %'] = display_df['Allocation %'].apply(lambda x: f"{x:.2f}%")
        
        # Format cost columns
        for col in display_df.columns:
            if 'cost' in col.lower() or 'spend' in col.lower():
                display_df[col] = display_df[col].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "")
        
        # Display the formatted dataframe
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )
        
        # Add download button for results
        csv = allocation_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Download Results CSV",
            data=csv,
            file_name="optimization_results.csv",
            mime="text/csv",
        )
    else:
        st.warning("No allocation data available in the results.")
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
    """Optimization weights and parameters section"""
    st.markdown("#### ⚖️ Optimization Weights")
    
    # Initialize sliders if not present
    if 'cost_slider' not in st.session_state:
        st.session_state.cost_slider = st.session_state.opt_cost_weight
    if 'performance_slider' not in st.session_state:
        st.session_state.performance_slider = st.session_state.opt_performance_weight
    
    # Cost vs Performance trade-off
    cost_weight = st.slider(
        "💰 Cost Weight",
        min_value=0,
        max_value=100,
        value=st.session_state.opt_cost_weight,
        step=5,
        key="cost_slider",
        help="How much to prioritize cost savings in the optimization",
        on_change=update_weights_callback
    )
    
    performance_weight = st.slider(
        "⭐ Performance Weight",
        min_value=0,
        max_value=100,
        value=st.session_state.opt_performance_weight,
        step=5,
        key="performance_slider", 
        help="How much to prioritize carrier performance in the optimization",
        on_change=update_weights_callback
    )
    
    # Visual indicator of weights
    st.progress(cost_weight / 100)
    col1, col2 = st.columns(2)
    col1.metric("Cost Importance", f"{cost_weight}%")
    col2.metric("Performance Importance", f"{performance_weight}%")

def update_weights_callback():
    """Callback to update weights in session state"""
    st.session_state.opt_cost_weight = st.session_state.cost_slider
    st.session_state.opt_performance_weight = st.session_state.performance_slider
    
    # Add normalized weights to session state (0.0-1.0 scale)
    st.session_state.normalized_cost_weight = st.session_state.cost_slider / 100.0
    st.session_state.normalized_performance_weight = st.session_state.performance_slider / 100.0

def show_carrier_constraints_section(final_filtered_data):
    """Unified constraints and limits section for all entity types"""
    st.markdown("#### 🚛 Carrier Capacity & Constraints")
    st.markdown("*Set minimum and maximum container limits across carriers, categories, and ports*")
    
    if len(final_filtered_data) == 0:
        st.warning("No data available for constraints")
        return
    
    # Extract all constraint entities
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
        scacs = [scac for scac in scacs if pd.notna(scac)]
    
    # Get unique categories if available
    categories = []
    if 'Category' in final_filtered_data.columns and not final_filtered_data['Category'].isna().all():
        categories = sorted(final_filtered_data['Category'].unique())
        categories = [category for category in categories if pd.notna(category)]
        
    # Get unique ports if available
    ports = []
    if 'Discharged Port' in final_filtered_data.columns and not final_filtered_data['Discharged Port'].isna().all():
        ports = sorted(final_filtered_data['Discharged Port'].unique())
        ports = [port for port in ports if pd.notna(port)]
    
    # Initialize session state for all constraint types if not already present
    if 'carrier_constraints' not in st.session_state:
        st.session_state.carrier_constraints = {}
    if 'scac_constraints' not in st.session_state:
        st.session_state.scac_constraints = {}
    if 'category_constraints' not in st.session_state:
        st.session_state.category_constraints = {}
    if 'port_constraints' not in st.session_state:
        st.session_state.port_constraints = {}
    
    # Create tabs for different constraint types
    constraint_tabs = st.tabs(["🏢 Carriers", "🏷️ Categories", "🚢 Ports"])
    
    # ============ TAB 1: CARRIERS ============
    with constraint_tabs[0]:
        # If carriers available, show carrier constraints
        if carriers:
            st.subheader("Carrier Constraints")
            
            # Show carriers in a table format with min/max inputs
            st.markdown("#### Carrier Container Allocation Limits")
            
            # Create a table-like layout with columns
            col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1.5, 1.5, 1.5])
            with col1:
                st.markdown("**Carrier**")
            with col2:
                st.markdown("**Volume**")
            with col3:
                st.markdown("**Rate**")
            with col4:
                st.markdown("**Min**")
            with col5:
                st.markdown("**Max**")
            
            # Add horizontal line
            st.markdown("---")
            
            # Create rows for each carrier
            for carrier in carriers:
                # Get carrier data
                if 'Carrier' in final_filtered_data.columns and carrier in final_filtered_data['Carrier'].values:
                    carrier_data = final_filtered_data[final_filtered_data['Carrier'] == carrier]
                elif 'Dray SCAC(FL)' in final_filtered_data.columns:
                    carrier_data = final_filtered_data[final_filtered_data['Dray SCAC(FL)'] == carrier]
                else:
                    carrier_data = pd.DataFrame()
                
                total_volume = carrier_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in carrier_data.columns and len(carrier_data) > 0) else 0
                avg_rate = carrier_data['Base Rate'].mean() if ('Base Rate' in carrier_data.columns and len(carrier_data) > 0) else 0
                
                # Format carrier for key
                carrier_str = str(carrier).replace(' ', '_')
                carrier_key = f"carrier_{carrier_str}"
                
                col1, col2, col3, col4, col5 = st.columns([3, 1.5, 1.5, 1.5, 1.5])
                
                with col1:
                    st.markdown(f"**{carrier}**")
                with col2:
                    st.markdown(f"{total_volume:,.0f}")
                with col3:
                    st.markdown(f"${avg_rate:,.2f}")
                with col4:
                    min_containers = st.number_input(
                        "Min",
                        min_value=0,
                        max_value=int(total_volume) if total_volume > 0 else 1000,
                        value=st.session_state.carrier_constraints.get(carrier, {}).get('min', 0),
                        step=10,
                        key=f"{carrier_key}_min",
                        label_visibility="collapsed"
                    )
                with col5:
                    max_containers = st.number_input(
                        "Max",
                        min_value=min_containers,
                        max_value=int(total_volume * 2) if total_volume > 0 else 2000,
                        value=st.session_state.carrier_constraints.get(carrier, {}).get('max', int(total_volume) if total_volume > 0 else 1000),
                        step=10,
                        key=f"{carrier_key}_max",
                        label_visibility="collapsed"
                    )
                
                # Update constraints in session state
                if carrier not in st.session_state.carrier_constraints:
                    st.session_state.carrier_constraints[carrier] = {}
                
                st.session_state.carrier_constraints[carrier]['min'] = min_containers
                st.session_state.carrier_constraints[carrier]['max'] = max_containers
        else:
            st.warning("No carriers found in data")
            
    # ============ TAB 2: CATEGORIES ============
    with constraint_tabs[1]:
        if categories:
            st.subheader("Category Constraints")
            
            # Show categories in a table format
            st.markdown("#### Category Container Allocation Limits")
            
            # Create a table-like layout with columns
            col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
            with col1:
                st.markdown("**Category**")
            with col2:
                st.markdown("**Volume**")
            with col3:
                st.markdown("**Min**")
            with col4:
                st.markdown("**Max**")
            
            # Add horizontal line
            st.markdown("---")
            
            # Create rows for each category
            for category in categories:
                category_data = final_filtered_data[final_filtered_data['Category'] == category]
                total_volume = category_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in category_data.columns and len(category_data) > 0) else 0
                
                # Format category for key
                category_str = str(category).replace(' ', '_')
                category_key = f"category_{category_str}"
                
                col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
                
                with col1:
                    st.markdown(f"**{category}**")
                with col2:
                    st.markdown(f"{total_volume:,.0f}")
                with col3:
                    category_min = st.number_input(
                        "Min",
                        min_value=0,
                        max_value=int(total_volume) if total_volume > 0 else 1000,
                        value=st.session_state.category_constraints.get(category, {}).get('min', 0),
                        step=10,
                        key=f"{category_key}_min",
                        label_visibility="collapsed"
                    )
                with col4:
                    category_max = st.number_input(
                        "Max",
                        min_value=category_min,
                        max_value=int(total_volume * 2) if total_volume > 0 else 2000,
                        value=st.session_state.category_constraints.get(category, {}).get('max', int(total_volume) if total_volume > 0 else 1000),
                        step=10,
                        key=f"{category_key}_max",
                        label_visibility="collapsed"
                    )
                
                # Update constraints in session state
                if category not in st.session_state.category_constraints:
                    st.session_state.category_constraints[category] = {}
                
                st.session_state.category_constraints[category]['min'] = category_min
                st.session_state.category_constraints[category]['max'] = category_max
        else:
            st.warning("No category data found")
    
    # ============ TAB 3: PORTS ============
    with constraint_tabs[2]:
        if ports:
            st.subheader("Port Constraints")
            
            # Show ports in a table format
            st.markdown("#### Port Container Allocation Limits")
            
            # Create a table-like layout with columns
            col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
            with col1:
                st.markdown("**Port**")
            with col2:
                st.markdown("**Volume**")
            with col3:
                st.markdown("**Min**")
            with col4:
                st.markdown("**Max**")
            
            # Add horizontal line
            st.markdown("---")
            
            # Create rows for each port
            for port in ports:
                port_data = final_filtered_data[final_filtered_data['Discharged Port'] == port]
                total_volume = port_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in port_data.columns and len(port_data) > 0) else 0
                
                # Format port for key
                port_str = str(port).replace(' ', '_')
                port_key = f"port_{port_str}"
                
                col1, col2, col3, col4 = st.columns([4, 2, 2, 2])
                
                with col1:
                    st.markdown(f"**{port}**")
                with col2:
                    st.markdown(f"{total_volume:,.0f}")
                with col3:
                    port_min = st.number_input(
                        "Min",
                        min_value=0,
                        max_value=int(total_volume) if total_volume > 0 else 1000,
                        value=st.session_state.port_constraints.get(port, {}).get('min', 0),
                        step=10,
                        key=f"{port_key}_min",
                        label_visibility="collapsed"
                    )
                with col4:
                    port_max = st.number_input(
                        "Max",
                        min_value=port_min,
                        max_value=int(total_volume * 2) if total_volume > 0 else 2000,
                        value=st.session_state.port_constraints.get(port, {}).get('max', int(total_volume) if total_volume > 0 else 1000),
                        step=10,
                        key=f"{port_key}_max",
                        label_visibility="collapsed"
                    )
                
                # Update constraints in session state
                if port not in st.session_state.port_constraints:
                    st.session_state.port_constraints[port] = {}
                
                st.session_state.port_constraints[port]['min'] = port_min
                st.session_state.port_constraints[port]['max'] = port_max
        else:
            st.warning("No port data found")
            
    # Show a summary of constraints that are set
    st.markdown("---")
    st.subheader("Constraint Summary")
    
    # Count constraints set
    carrier_constraints_count = sum(1 for c in st.session_state.carrier_constraints.values() if c.get('min', 0) > 0 or c.get('max', 0) < float('inf'))
    category_constraints_count = sum(1 for c in st.session_state.category_constraints.values() if c.get('min', 0) > 0 or c.get('max', 0) < float('inf'))
    port_constraints_count = sum(1 for c in st.session_state.port_constraints.values() if c.get('min', 0) > 0 or c.get('max', 0) < float('inf'))
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Carrier Constraints", carrier_constraints_count)
    with col2:
        st.metric("Category Constraints", category_constraints_count)
    with col3:
        st.metric("Port Constraints", port_constraints_count)

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
            width='stretch'
        ):
            run_unified_optimization(final_filtered_data)
    
    with col2:
        if st.button("🔄 Reset", help="Clear all results and constraints", width='stretch'):
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
            "Average Performance",
            f"{results['avg_performance']:.2f}",
            delta=f"{results.get('performance_change', 0):+.2f}" if 'performance_change' in results else None
        )
    
    # Show allocation details
    if 'allocation_df' in results and not results['allocation_df'].empty:
        st.markdown("#### 📋 Allocation Details")
        
        # Format the allocation dataframe
        allocation_df = results['allocation_df'].copy()
        
        # Add percentage column
        if 'Containers' in allocation_df.columns:
            total_containers = allocation_df['Containers'].sum()
            allocation_df['Percentage'] = (allocation_df['Containers'] / total_containers * 100).round(1)
            allocation_df['Percentage'] = allocation_df['Percentage'].astype(str) + '%'
        
        # Format cost as currency
        if 'Cost' in allocation_df.columns:
            allocation_df['Cost'] = allocation_df['Cost'].map('${:,.2f}'.format)
        
        # Show as dataframe
        st.dataframe(
            allocation_df,
            column_config={
                "Combined_Score": st.column_config.ProgressColumn(
                    "Score",
                    min_value=0,
                    max_value=1,
                    format="%.2f"
                ),
            },
            width='stretch'
        )
        
        # Download option
        csv = allocation_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Allocation Details",
            data=csv,
            file_name="optimization_results.csv",
            mime="text/csv",
            width='stretch'
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
            
        # Make sure we have Total_Lane_Volume, or add it if needed
        if 'Total_Lane_Volume' not in data.columns:
            if 'Container Count' in data.columns:
                data['Total_Lane_Volume'] = data['Container Count']
            else:
                # Default to 1 per row if no volume information
                data['Total_Lane_Volume'] = 1
        
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
                
        # Pre-allocate minimum containers to ports with constraints
        port_allocation = {}
        for port, port_constraint in port_constraints.items():
            min_port_containers = port_constraint.get('min', 0)
            if min_port_containers > 0:
                port_allocation[port] = min_port_containers
                remaining_containers -= min_port_containers
        
        # Pre-allocate minimum containers to categories with constraints
        category_allocation = {}
        for category, category_constraint in category_constraints.items():
            min_category_containers = category_constraint.get('min', 0)
            if min_category_containers > 0:
                category_allocation[category] = min_category_containers
                remaining_containers -= min_category_containers
        
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
            carrier_volume = carrier_data['Total_Lane_Volume'].sum() if ('Total_Lane_Volume' in carrier_data.columns and len(carrier_data) > 0) else 0
            available_capacity = min(max_containers, carrier_volume)
            
            # Allocate containers
            allocated = min(available_capacity, remaining_containers)
            allocated = max(allocated, min_containers if remaining_containers >= min_containers else 0)
            
            if allocated > 0:
                remaining_containers -= allocated
                
                # Calculate metrics for this allocation
                carrier_cost = carrier_data['Base Rate'].iloc[0] * allocated if len(carrier_data) > 0 and 'Base Rate' in carrier_data.columns else 0
                carrier_performance = carrier_data['Performance_Score'].iloc[0] if len(carrier_data) > 0 and 'Performance_Score' in carrier_data.columns else 0
                combined_score = carrier_data['combined_score'].iloc[0] if len(carrier_data) > 0 and 'combined_score' in carrier_data.columns else 0
                
                allocation_results.append({
                    'Carrier': carrier,
                    'Containers': allocated,
                    'Cost': carrier_cost,
                    'Performance': carrier_performance,
                    'Combined_Score': combined_score
                })
                
                if remaining_containers <= 0:
                    break
        
        # Calculate summary metrics
        if allocation_results:
            total_cost = sum([r['Cost'] for r in allocation_results])
            total_allocated = sum([r['Containers'] for r in allocation_results])
            avg_performance = sum([r['Performance'] * r['Containers'] for r in allocation_results]) / total_allocated if total_allocated > 0 else 0
        else:
            total_cost = 0
            total_allocated = 0
            avg_performance = 0
        
        allocation_df = pd.DataFrame(allocation_results)
        
        return {
            'success': True,
            'total_cost': total_cost,
            'containers_allocated': total_allocated,
            'allocation_rate': (total_allocated / total_containers * 100) if total_containers > 0 else 0,
            'avg_performance': avg_performance,
            'allocation_df': allocation_df,
            'remaining_containers': remaining_containers
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def reset_optimization_state():
    """Reset all optimization state"""
    keys_to_reset = [
        'opt_cost_weight', 'opt_performance_weight',
        'carrier_constraints', 'optimization_results',
        'normalized_cost_weight', 'normalized_performance_weight',
        'scac_constraints', 'category_constraints', 'port_constraints'  # Added port_constraints
    ]
    
    for key in keys_to_reset:
        if key in st.session_state:
            del st.session_state[key]

# Legacy functions for backward compatibility
def show_optimization_context(final_filtered_data):
    """Legacy function - now part of unified interface"""
    pass

def show_optimization_parameters_ui():
    """Legacy function - now part of unified interface"""
    return 0.7, 0.3

def show_container_constraints_ui(final_filtered_data):
    """Legacy function - now part of unified interface"""
    pass

def show_container_type_restrictions_ui(final_filtered_data):
    """Legacy function - now part of unified interface"""
    pass

def show_missing_rate_analysis_for_optimization(final_filtered_data):
    """Legacy function for missing rate analysis"""
    pass
