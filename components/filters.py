"""
Filtering module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header

def initialize_filter_session_state():
    """Initialize session state for filters"""
    if 'filter_ports' not in st.session_state:
        st.session_state.filter_ports = []
    if 'filter_fcs' not in st.session_state:
        st.session_state.filter_fcs = []
    if 'filter_weeks' not in st.session_state:
        st.session_state.filter_weeks = []
    if 'filter_scacs' not in st.session_state:
        st.session_state.filter_scacs = []
    if 'filters_applied' not in st.session_state:
        st.session_state.filters_applied = False
    if 'rate_type' not in st.session_state:
        st.session_state.rate_type = 'Base Rate'  # Default to Base Rate

def show_rate_type_selector(comprehensive_data):
    """Show rate type selector to switch between Base Rate and CPC"""
    # Initialize rate_type in session state if not exists
    if 'rate_type' not in st.session_state:
        st.session_state.rate_type = 'Base Rate'
    
    # Check if CPC data exists
    has_cpc = 'CPC' in comprehensive_data.columns and comprehensive_data['CPC'].sum() > 0
    
    if has_cpc:
        section_header("💰 Rate Type Selection")
        st.markdown("""
        **Select which rate type to use for all calculations and cost analysis:**
        - **Base Rate**: Standard freight rates
        - **CPC (Cost Per Container)**: Per-container cost rates
        """)
        
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            # Get current index safely
            current_index = 0 if st.session_state.rate_type == 'Base Rate' else 1
            
            rate_type = st.radio(
                "Rate Type for Calculations",
                options=['Base Rate', 'CPC'],
                index=current_index,
                horizontal=True,
                key='rate_type_selector'
            )
            
            if rate_type != st.session_state.rate_type:
                st.session_state.rate_type = rate_type
                st.rerun()
        
        with col2:
            if rate_type == 'Base Rate':
                st.metric("📊 Current Rate Type", "Base Rate")
            else:
                st.metric("📊 Current Rate Type", "CPC")
        
        with col3:
            total_value = comprehensive_data['Total Rate'].sum() if rate_type == 'Base Rate' else comprehensive_data['Total CPC'].sum()
            st.metric("💵 Total Cost", f"${total_value:,.2f}")
        
        st.markdown("---")
    else:
        # No CPC data, default to Base Rate
        st.session_state.rate_type = 'Base Rate'

@st.fragment
def filter_interface_fragment(comprehensive_data):
    """Filter interface as a fragment to prevent full page reloads"""
    
    # Add search functionality
    st.markdown("**Search and Filter Options:**")
    search_col1, search_col2 = st.columns([1, 3])

    with search_col1:
        apply_filters = st.button("🔍 Apply Filters", type="primary", use_container_width=True)

    with search_col2:
        st.write("*Select your filters below and click 'Apply Filters' to update the results*")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        # Port filter with search
        st.markdown("**🚢 Ports:**")
        port_search = st.text_input("Search ports...", key="port_search", placeholder="Type to search ports")
        
        port_options = sorted(list(comprehensive_data['Discharged Port'].unique()))
        if port_search:
            port_options = [port for port in port_options if port_search.lower() in str(port).lower()]
        
        # Use session state as default without triggering rerun
        port_display_options = ['All'] + port_options
        
        # Get current selection without triggering rerun
        current_port_selection = st.multiselect(
            "Select Port(s)", 
            port_display_options, 
            default=['All'] if not st.session_state.filter_ports else st.session_state.filter_ports,
            key="port_multiselect"
        )

    with col2:
        # FC filter with search
        st.markdown("**🏭 Facilities:**")
        fc_search = st.text_input("Search facilities...", key="fc_search", placeholder="Type to search facilities")
        
        fc_options = sorted(list(comprehensive_data['Facility'].str[:4].unique()))
        if fc_search:
            fc_options = [fc for fc in fc_options if fc_search.lower() in str(fc).lower()]
        
        fc_display_options = ['All'] + fc_options
        
        current_fc_selection = st.multiselect(
            "Select FC (Facility)", 
            fc_display_options, 
            default=['All'] if not st.session_state.filter_fcs else st.session_state.filter_fcs,
            key="fc_multiselect"
        )

    with col3:
        # Week filter with search
        st.markdown("**📅 Week Numbers:**")
        week_search = st.text_input("Search weeks...", key="week_search", placeholder="Type to search weeks")
        
        week_options = sorted(list(comprehensive_data['Week Number'].unique()))
        if week_search:
            week_options = [week for week in week_options if week_search.lower() in str(week).lower()]
        
        week_display_options = ['All'] + [str(week) for week in week_options]
        
        current_week_selection = st.multiselect(
            "Select Week Number(s)", 
            week_display_options, 
            default=['All'] if not st.session_state.filter_weeks else [str(w) for w in st.session_state.filter_weeks],
            key="week_multiselect"
        )

    with col4:
        # SCAC filter with search
        st.markdown("**🚛 SCACs:**")
        scac_search = st.text_input("Search SCACs...", key="scac_search", placeholder="Type to search SCACs")
        
        scac_options = sorted(list(comprehensive_data['Dray SCAC(FL)'].unique()))
        if scac_search:
            scac_options = [scac for scac in scac_options if scac_search.lower() in str(scac).lower()]
        
        scac_display_options = ['All'] + scac_options
        
        current_scac_selection = st.multiselect(
            "Select Dray SCAC(FL)", 
            scac_display_options, 
            default=['All'] if not st.session_state.filter_scacs else st.session_state.filter_scacs,
            key="scac_multiselect"
        )

    # Clear filters button
    if st.button("🗑️ Clear All Filters", use_container_width=True):
        st.session_state.filter_ports = []
        st.session_state.filter_fcs = []
        st.session_state.filter_weeks = []
        st.session_state.filter_scacs = []
        st.session_state.filters_applied = True
        st.rerun()

    # Apply filters when button is clicked
    if apply_filters:
        # Check if filters actually changed
        new_ports = [p for p in current_port_selection if p != 'All']
        new_fcs = [f for f in current_fc_selection if f != 'All']
        new_weeks = [int(w) for w in current_week_selection if w != 'All']
        new_scacs = [s for s in current_scac_selection if s != 'All']
        
        # Only update if filters changed
        filters_changed = (
            new_ports != st.session_state.filter_ports or
            new_fcs != st.session_state.filter_fcs or
            new_weeks != st.session_state.filter_weeks or
            new_scacs != st.session_state.filter_scacs
        )
        
        if filters_changed:
            st.session_state.filter_ports = new_ports
            st.session_state.filter_fcs = new_fcs
            st.session_state.filter_weeks = new_weeks
            st.session_state.filter_scacs = new_scacs
            st.session_state.filters_applied = True
            st.success("✅ Filters applied successfully!")
            st.rerun()
        else:
            st.info("ℹ️ No changes detected in filters.")

def show_optimization_settings():
    """Display optimization parameter sliders - FORM VERSION (prevents auto-reload)"""
    st.markdown("### 🎯 Linear Programming Optimization Settings")
    st.markdown("""
    Configure the weights and constraints for the **Optimized** scenario in the Detailed Analysis Table.
    These settings control how the LP optimization balances cost vs performance and limits carrier growth.
    
    ⚠️ **Note**: Adjust the sliders below and click "Run Optimization" to apply changes.
    """)
    
    # Initialize session state for ACTIVE optimization settings (used by calculations)
    if 'opt_cost_weight' not in st.session_state:
        st.session_state.opt_cost_weight = 70
    if 'opt_performance_weight' not in st.session_state:
        st.session_state.opt_performance_weight = 30
    if 'opt_max_growth_pct' not in st.session_state:
        st.session_state.opt_max_growth_pct = 30
    
    # Show current ACTIVE configuration first
    st.markdown("#### 📊 Current Active Configuration")
    st.caption("These are the settings currently being used for optimization")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("💰 Cost Weight", f"{st.session_state.opt_cost_weight}%")
    with col2:
        st.metric("🏆 Performance Weight", f"{st.session_state.opt_performance_weight}%")
    with col3:
        st.metric("🔒 Max Growth", f"{st.session_state.opt_max_growth_pct}%")
    
    st.markdown("---")
    
    # Use a form to prevent automatic reruns when sliders change
    with st.form(key='optimization_settings_form'):
        st.markdown("#### ⚖️ Optimization Weights")
        st.markdown("*How much should the optimization prioritize cost vs performance?*")
        
        # Cost Weight Slider - uses current active value as default
        cost_weight = st.slider(
            "💰 Cost Priority (%)",
            min_value=0,
            max_value=100,
            value=st.session_state.opt_cost_weight,
            step=5,
            help="Higher values prioritize carriers with better rates. Lower values focus more on performance.",
            key='cost_weight_slider'
        )
        
        # Performance Weight Slider (auto-calculated to sum to 100%)
        performance_weight = 100 - cost_weight
        st.slider(
            "🏆 Performance Priority (%)",
            min_value=0,
            max_value=100,
            value=performance_weight,
            step=5,
            disabled=True,
            help="Automatically calculated as 100% - Cost Priority",
            key='performance_weight_display'
        )
        
        st.markdown("#### 📈 Growth Constraint")
        st.markdown("*Maximum allowed growth above historical allocation*")
        
        # Max Growth Percentage Slider - uses current active value as default
        max_growth = st.slider(
            "🔒 Maximum Growth Cap (%)",
            min_value=0,
            max_value=100,
            value=st.session_state.opt_max_growth_pct,
            step=5,
            help="Limits how much a carrier's allocation can grow beyond their historical baseline. E.g., 30% means a carrier with 40% historical share can get up to 52% (40% × 1.30).",
            key='max_growth_slider'
        )
        
        # Show example inside the form
        st.markdown("---")
        st.markdown("#### 💡 Example Impact")
        example_historical = 40
        example_max = example_historical * (1 + max_growth / 100)
        
        st.info(f"""
        **Example**: If a carrier historically handled **{example_historical}%** of a lane's volume:
        - With {max_growth}% growth cap, they can receive up to **{example_max:.1f}%** in the optimized scenario
        - Additional volume beyond {example_max:.1f}% will cascade to the next-best carrier
        """)
        
        st.markdown("---")
        
        # Form buttons - inside the form
        col1, col2 = st.columns([2, 1])
        
        with col1:
            # Submit button for the form (Run Optimization)
            run_optimization = st.form_submit_button(
                "▶️ Run Optimization", 
                use_container_width=True, 
                type="primary"
            )
        
        with col2:
            # Reset button
            reset_defaults = st.form_submit_button(
                "🔄 Reset to Defaults", 
                use_container_width=True
            )
    
    # Handle form submission OUTSIDE the form
    if run_optimization:
        # Check if values actually changed
        has_changes = (
            cost_weight != st.session_state.opt_cost_weight or
            max_growth != st.session_state.opt_max_growth_pct
        )
        
        if has_changes:
            # Apply changes to active optimization settings
            st.session_state.opt_cost_weight = cost_weight
            st.session_state.opt_performance_weight = performance_weight
            st.session_state.opt_max_growth_pct = max_growth
            st.success("✅ Optimization settings updated! The Optimized scenario will now use these new settings.")
            st.rerun()
        else:
            st.info("ℹ️ No changes detected - settings remain the same.")
    
    if reset_defaults:
        # Reset to default values
        st.session_state.opt_cost_weight = 70
        st.session_state.opt_performance_weight = 30
        st.session_state.opt_max_growth_pct = 30
        st.success("✅ Settings reset to defaults (70% cost, 30% performance, 30% growth cap)")
        st.rerun()

def show_filter_interface(comprehensive_data):
    """Display the filter interface"""
    section_header("🔍 Filters & Optimization")
    
    # Tabs for Filters and Optimization Settings
    tab1, tab2 = st.tabs(["🔍 Data Filters", "🧮 Optimization Settings"])
    
    with tab1:
        initialize_filter_session_state()
        # Use the fragment for the filter interface
        filter_interface_fragment(comprehensive_data)
    
    with tab2:
        show_optimization_settings()

def apply_filters_to_data(comprehensive_data):
    """Apply session state filters to the data"""
    # Use copy only if filters are actually applied - otherwise return view
    has_filters = bool(
        st.session_state.filter_ports or 
        st.session_state.filter_fcs or 
        st.session_state.filter_weeks or 
        st.session_state.filter_scacs
    )
    
    if not has_filters:
        # No filters - return original data without copy
        return (comprehensive_data, "All Ports", "All FCs", "All Weeks", "All SCACs")
    
    # Create boolean masks for efficient filtering
    mask = pd.Series(True, index=comprehensive_data.index)
    
    # Apply port filter
    if st.session_state.filter_ports:
        mask &= comprehensive_data['Discharged Port'].isin(st.session_state.filter_ports)
        display_ports = st.session_state.filter_ports
    else:
        display_ports = "All Ports"

    # Apply FC filter
    if st.session_state.filter_fcs:
        mask &= comprehensive_data['Facility'].str[:4].isin(st.session_state.filter_fcs)
        display_fcs = st.session_state.filter_fcs
    else:
        display_fcs = "All FCs"

    # Apply week filter
    if st.session_state.filter_weeks:
        mask &= comprehensive_data['Week Number'].isin(st.session_state.filter_weeks)
        display_weeks = st.session_state.filter_weeks
    else:
        display_weeks = "All Weeks"

    # Apply SCAC filter
    if st.session_state.filter_scacs:
        mask &= comprehensive_data['Dray SCAC(FL)'].isin(st.session_state.filter_scacs)
        display_scacs = st.session_state.filter_scacs
    else:
        display_scacs = "All SCACs"

    filtered_data = comprehensive_data[mask].copy()
    
    return filtered_data, display_ports, display_fcs, display_weeks, display_scacs

def show_selection_summary(display_ports, display_fcs, display_weeks, display_scacs, final_filtered_data):
    """Show summary of current selection"""
    section_header("📋 Selection Summary")
    summary_col1, summary_col2 = st.columns(2)

    with summary_col1:
        st.write(f"**Ports:** {display_ports}")
        st.write(f"**FCs (Facilities):** {display_fcs}")

    with summary_col2:
        st.write(f"**Week Numbers:** {display_weeks}")
        st.write(f"**SCACs:** {display_scacs}")

    st.write(f"**Total Records:** {len(final_filtered_data):,}")
