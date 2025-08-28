"""
Filtering module for the Carrier Tender Optimization Dashboard
"""
import streamlit as st
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

def show_filter_interface(comprehensive_data):
    """Display the filter interface"""
    section_header("🔍 Filters")
    initialize_filter_session_state()
    
    # Use the fragment for the filter interface
    filter_interface_fragment(comprehensive_data)

def apply_filters_to_data(comprehensive_data):
    """Apply session state filters to the data"""
    # Apply filters to data
    filtered_data = comprehensive_data.copy()

    # Apply port filter
    if st.session_state.filter_ports:
        filtered_data = filtered_data[filtered_data['Discharged Port'].isin(st.session_state.filter_ports)]
        display_ports = st.session_state.filter_ports
    else:
        display_ports = "All Ports"

    # Apply FC filter
    if st.session_state.filter_fcs:
        fc_mask = filtered_data['Facility'].str[:4].isin(st.session_state.filter_fcs)
        filtered_data = filtered_data[fc_mask]
        display_fcs = st.session_state.filter_fcs
    else:
        display_fcs = "All FCs"

    # Apply week filter
    if st.session_state.filter_weeks:
        filtered_data = filtered_data[filtered_data['Week Number'].isin(st.session_state.filter_weeks)]
        display_weeks = st.session_state.filter_weeks
    else:
        display_weeks = "All Weeks"

    # Apply SCAC filter
    if st.session_state.filter_scacs:
        filtered_data = filtered_data[filtered_data['Dray SCAC(FL)'].isin(st.session_state.filter_scacs)]
        display_scacs = st.session_state.filter_scacs
    else:
        display_scacs = "All SCACs"

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
