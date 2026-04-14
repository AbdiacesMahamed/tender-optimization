"""
Peel Pile Analysis module — identifies and allocates high-volume vessel groups.

Extracted from metrics.py to keep analysis, UI, and constraint-application logic
in a focused, debuggable file.
"""
import streamlit as st
import pandas as pd
from .config_styling import section_header
from .utils import count_containers


def show_peel_pile_analysis(data):
    """
    Show Peel Pile Analysis table and allocation UI.
    This is the display-only portion. The actual constraint application
    happens via apply_peel_pile_as_constraints() in the dashboard pipeline.
    
    Args:
        data: DataFrame containing container data with Vessel column (should be filtered data)
    """
    if 'Vessel' not in data.columns:
        return  # Vessel column not available, skip this analysis
    
    st.markdown("---")
    section_header("📦 Peel Pile Analysis")
    
    # Initialize peel pile allocations in session state
    if 'peel_pile_allocations' not in st.session_state:
        st.session_state.peel_pile_allocations = {}
    
    # Calculate container count per Vessel
    if 'Container Numbers' in data.columns:
        data_copy = data.copy()
        data_copy['_container_count'] = data_copy['Container Numbers'].apply(count_containers)
    else:
        data_copy = data.copy()
        data_copy['_container_count'] = data_copy['Container Count']
    
    # Build grouping columns: Vessel + Week + Port + Terminal
    group_cols = ['Vessel']
    if 'Category' in data_copy.columns:
        group_cols.append('Category')
    if 'Week Number' in data_copy.columns:
        group_cols.append('Week Number')
    if 'Discharged Port' in data_copy.columns:
        group_cols.append('Discharged Port')
    if 'Terminal' in data_copy.columns:
        group_cols.append('Terminal')
    
    # Group by Vessel + Week + Port + Terminal and sum containers
    vessel_summary = data_copy.groupby(group_cols).agg({
        '_container_count': 'sum',
    }).reset_index()
    vessel_summary = vessel_summary.rename(columns={'_container_count': 'Container Count'})
    
    # Filter for peel pile (30+ containers)
    peel_pile = vessel_summary[vessel_summary['Container Count'] >= 30].copy()
    peel_pile = peel_pile.sort_values('Container Count', ascending=False)
    
    if len(peel_pile) == 0:
        st.info("ℹ️ No Vessel groups meet the peel pile threshold (30+ containers per Week/Port).")
        return
    
    # Get available carriers from the data
    carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in data.columns else 'Carrier'
    all_carriers = sorted([c for c in data[carrier_col].dropna().unique() if str(c).strip()])
    
    # Add "Assigned Carrier" column to display based on session state
    display_cols = group_cols + ['Container Count']
    display_peel = peel_pile[display_cols].copy()
    
    # Build allocation key for each row and add assigned carrier info
    assigned_carriers = []
    split_info = []
    for _, row in peel_pile.iterrows():
        key = _peel_pile_key(row, group_cols)
        assigned = st.session_state.peel_pile_allocations.get(key, None)
        # Normalize legacy single-carrier strings to list
        if isinstance(assigned, str):
            assigned = [assigned]
        if assigned and len(assigned) > 0:
            assigned_carriers.append(', '.join(assigned))
            total = int(row['Container Count'])
            n = len(assigned)
            per_carrier = total // n
            remainder = total % n
            if n == 1:
                split_info.append(f"All {total}")
            elif remainder == 0:
                split_info.append(f"{per_carrier} each ({n}-way)")
            else:
                split_info.append(f"{per_carrier+1}/{per_carrier} ({n}-way)")
        else:
            assigned_carriers.append('—')
            split_info.append('—')
    display_peel['Assigned Carrier'] = assigned_carriers
    display_peel['Split'] = split_info
    
    # Format container count for display
    display_fmt = display_peel.copy()
    display_fmt['Container Count'] = display_fmt['Container Count'].apply(lambda x: f"{x:,.0f}")
    
    st.dataframe(display_fmt, use_container_width=True, hide_index=True)
    
    # Show how many are actively constraining
    active_count = sum(1 for v in st.session_state.peel_pile_allocations.values() if v and (len(v) > 0 if isinstance(v, list) else True))
    if active_count > 0:
        st.success(f"🔒 {active_count} peel pile allocation(s) active — these are applied as constraints in the analysis above.")
    
    # ==================== ALLOCATION UI (fragment — reruns independently) ====================
    @st.fragment
    def _peel_pile_allocation_ui():
        st.markdown("#### 🚛 Allocate Peel Pile to Carrier(s)")
        st.caption("Pick a peel pile group and one or more carriers, then click 'Add to Queue'. Containers are split equally across selected carriers. Queue up as many as you need, then click 'Apply All' to lock them as constraints.")
        
        # Initialize pending queue in session state (not yet applied)
        if 'peel_pile_pending' not in st.session_state:
            st.session_state.peel_pile_pending = {}
        
        # Build human-readable labels and keys for each peel pile row
        _label_map = {
            'Vessel': lambda r: f"Vessel: {r['Vessel']}",
            'Category': lambda r: f"Cat: {r['Category']}",
            'Week Number': lambda r: f"Wk {int(r['Week Number'])}",
            'Discharged Port': lambda r: f"Port: {r['Discharged Port']}",
            'Terminal': lambda r: f"Terminal: {r['Terminal']}",
        }
        peel_labels_inner = []
        peel_keys_inner = []
        for _, row in peel_pile.iterrows():
            parts = [_label_map[col](row) for col in group_cols if col in _label_map]
            parts.append(f"({int(row['Container Count'])} containers)")
            peel_labels_inner.append(" | ".join(parts))
            peel_keys_inner.append(_peel_pile_key(row, group_cols))
        
        # Dropdowns
        col1, col2 = st.columns([3, 2])
        
        with col1:
            selected_idx = st.selectbox(
                "Select Peel Pile Group",
                range(len(peel_labels_inner)),
                format_func=lambda i: peel_labels_inner[i],
                key="peel_pile_select"
            )
        
        with col2:
            selected_carriers = st.multiselect(
                "Assign to Carrier(s) (SCAC)",
                all_carriers,
                key="peel_pile_carrier"
            )
        
        # Add to Queue — only reruns this fragment, not the full page
        if st.button("➕ Add to Queue", use_container_width=True, key="peel_pile_queue"):
            if selected_carriers:
                key = peel_keys_inner[selected_idx]
                st.session_state.peel_pile_pending[key] = selected_carriers
            else:
                st.warning("⚠️ Select at least one carrier.")
        
        # Show the pending queue
        combined_queue = dict(st.session_state.peel_pile_allocations)
        combined_queue.update(st.session_state.peel_pile_pending)
        
        if combined_queue:
            st.markdown("**📋 Queued Assignments:**")
            queue_rows = []
            for key, carriers in combined_queue.items():
                # Normalize legacy single-carrier strings to list
                if isinstance(carriers, str):
                    carriers = [carriers]
                label = None
                for k, lbl in zip(peel_keys_inner, peel_labels_inner):
                    if k == key:
                        label = lbl
                        break
                if label is None:
                    label = ' | '.join(str(v) for v in key)
                is_new = key in st.session_state.peel_pile_pending
                is_existing = key in st.session_state.peel_pile_allocations
                if is_new and not is_existing:
                    status = '🆕 New'
                elif is_new and is_existing and st.session_state.peel_pile_allocations.get(key) != carriers:
                    status = '✏️ Changed'
                else:
                    status = '✅ Applied'
                carrier_display = ', '.join(carriers)
                split_label = f"Equal {len(carriers)}-way" if len(carriers) > 1 else "100%"
                queue_rows.append({'Peel Pile Group': label, 'Carriers': carrier_display, 'Split': split_label, 'Status': status})
            
            queue_df = pd.DataFrame(queue_rows)
            st.dataframe(queue_df, use_container_width=True, hide_index=True)
        
        # Action buttons
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 1])
        
        with btn_col1:
            if st.button("✅ Apply All", type="primary", use_container_width=True, key="peel_pile_apply"):
                st.session_state.peel_pile_allocations.update(st.session_state.peel_pile_pending)
                st.session_state.peel_pile_pending = {}
                st.rerun()  # full rerun to recalculate pipeline
        
        with btn_col2:
            if st.button("🗑️ Clear Queue", use_container_width=True, key="peel_pile_clear_queue"):
                st.session_state.peel_pile_pending = {}
                st.rerun(scope="fragment")
        
        with btn_col3:
            if st.button("🗑️ Clear All", use_container_width=True, key="peel_pile_clear_all"):
                st.session_state.peel_pile_allocations = {}
                st.session_state.peel_pile_pending = {}
                st.rerun()  # full rerun to recalculate pipeline
    
    _peel_pile_allocation_ui()
    
    # ==================== EXPORT ====================
    export_peel = peel_pile.copy()
    assigned_export = []
    split_export = []
    for _, row in peel_pile.iterrows():
        key = _peel_pile_key(row, group_cols)
        carriers = st.session_state.peel_pile_allocations.get(key, None)
        if isinstance(carriers, str):
            carriers = [carriers]
        if carriers and len(carriers) > 0:
            assigned_export.append(', '.join(carriers))
            total = int(row['Container Count'])
            n = len(carriers)
            per_carrier = total // n
            remainder = total % n
            if n == 1:
                split_export.append(f"All {total}")
            elif remainder == 0:
                split_export.append(f"{per_carrier} each ({n}-way)")
            else:
                split_export.append(f"{per_carrier+1}/{per_carrier} ({n}-way)")
        else:
            assigned_export.append('')
            split_export.append('')
    export_peel['Assigned Carriers'] = assigned_export
    export_peel['Split'] = split_export
    
    csv = export_peel.to_csv(index=False)
    st.download_button(
        label="📥 Download Peel Pile",
        data=csv,
        file_name='peel_pile.csv',
        mime='text/csv',
        use_container_width=True
    )


def apply_peel_pile_as_constraints(filtered_data, constrained_data, unconstrained_data, constraint_summary):
    """
    Apply peel pile allocations from session state as constraints.
    
    Supports splitting a peel pile group across multiple carriers with equal split.
    Matching rows are divided evenly among the selected carriers. Any remainder
    rows (from integer division) stay in the unconstrained pool.
    
    This mirrors the constraint processor behavior:
    - Matching rows are moved from unconstrained_data to constrained_data
    - The carrier on those rows is reassigned to the chosen SCAC(s)
    - Each carrier is added to max_constrained_carriers so optimization skips it
    
    Args:
        filtered_data: Full filtered dataset (for reference)
        constrained_data: Existing constrained DataFrame (may be empty)
        unconstrained_data: Existing unconstrained DataFrame
        constraint_summary: Existing constraint summary list
    
    Returns:
        tuple: (constrained_data, unconstrained_data, constraint_summary, peel_pile_carriers)
               peel_pile_carriers is a set of carrier names that were assigned peel pile volume
    """
    peel_pile_allocations = st.session_state.get('peel_pile_allocations', {})
    peel_pile_carriers = set()
    
    if not peel_pile_allocations:
        return constrained_data, unconstrained_data, constraint_summary, peel_pile_carriers
    
    carrier_col = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in unconstrained_data.columns else 'Carrier'
    
    # Work on copies
    remaining = unconstrained_data.copy()
    new_constrained_rows = []
    
    for alloc_key, target_carriers in peel_pile_allocations.items():
        if not target_carriers:
            continue
        
        # Normalize legacy single-carrier strings to list
        if isinstance(target_carriers, str):
            target_carriers = [target_carriers]
        
        # Parse the key back into filter values
        # New format: ((col_name, value), (col_name, value), ...)
        # Legacy format: (value, value, ...) — plain strings, positional order
        key_pairs = list(alloc_key)
        
        # Detect legacy keys: if the first element is a string instead of a tuple
        if key_pairs and isinstance(key_pairs[0], str):
            _legacy_cols = ['Vessel', 'Week Number', 'Discharged Port', 'Terminal']
            key_pairs = [(col, val) for col, val in zip(_legacy_cols[:len(key_pairs)], key_pairs)]
        
        key_values = [v for _, v in key_pairs]
        
        # Build mask to find matching rows in unconstrained data
        mask = pd.Series(True, index=remaining.index)
        
        for col_name, col_value in key_pairs:
            if col_name not in remaining.columns:
                continue
            if col_name == 'Week Number':
                try:
                    week_val = float(col_value)
                    mask &= remaining['Week Number'] == week_val
                except (ValueError, TypeError):
                    mask &= remaining['Week Number'].astype(str) == col_value
            else:
                mask &= remaining[col_name].astype(str) == col_value
        
        matched_rows = remaining[mask]
        
        if len(matched_rows) == 0:
            continue
        
        num_carriers = len(target_carriers)
        total_rows = len(matched_rows)
        base_per_carrier = total_rows // num_carriers
        remainder_count = total_rows % num_carriers
        
        # Build description parts for constraint summary
        _short_names = {'Vessel': 'Vessel', 'Category': 'Cat', 'Week Number': 'Wk', 'Discharged Port': 'Port', 'Terminal': 'Terminal'}
        desc_parts = [f"{_short_names.get(c, c)}={v}" for c, v in key_pairs]
        
        # Split matched rows across carriers
        matched_indices = matched_rows.index.tolist()
        assigned_indices = set()
        offset = 0
        
        for i, carrier in enumerate(target_carriers):
            count_for_carrier = base_per_carrier + (1 if i < remainder_count else 0)
            carrier_indices = matched_indices[offset:offset + count_for_carrier]
            offset += count_for_carrier
            
            if not carrier_indices:
                continue
            
            carrier_rows = remaining.loc[carrier_indices]
            
            # Move these rows to constrained, reassigning carrier
            for idx in carrier_indices:
                row = remaining.loc[idx]
                constrained_row = row.copy()
                constrained_row[carrier_col] = carrier
                if 'Carrier' in constrained_row.index and carrier_col != 'Carrier':
                    constrained_row['Carrier'] = carrier
                
                split_desc = f" (equal split {num_carriers}-way)" if num_carriers > 1 else ""
                constrained_row['Constraint_Description'] = f"Peel Pile: {key_values[0]} → {carrier}{split_desc}"
                new_constrained_rows.append(constrained_row)
                assigned_indices.add(idx)
            
            container_count = carrier_rows['Container Count'].sum()
            peel_pile_carriers.add(carrier)
            
            # Add per-carrier constraint summary entry
            if num_carriers > 1:
                method_desc = f'Equal Split {num_carriers}-way'
                carrier_desc = f"Peel Pile: {', '.join(desc_parts)} → {carrier} ({i+1}/{num_carriers})"
            else:
                method_desc = '100% Allocation'
                carrier_desc = f"Peel Pile: {', '.join(desc_parts)} → {carrier}"
            
            constraint_summary.append({
                'priority': 'Peel Pile',
                'description': carrier_desc,
                'method': method_desc,
                'status': 'Applied',
                'containers_allocated': int(container_count),
                'target_containers': int(container_count),
            })
        
        # Remove all assigned rows from remaining
        remaining = remaining.drop(index=list(assigned_indices))
    
    # Merge new constrained rows with existing constrained data
    if new_constrained_rows:
        new_constrained_df = pd.DataFrame(new_constrained_rows)
        if len(constrained_data) > 0:
            constrained_data = pd.concat([constrained_data, new_constrained_df], ignore_index=True)
        else:
            constrained_data = new_constrained_df
    
    return constrained_data, remaining, constraint_summary, peel_pile_carriers


def _peel_pile_key(row, group_cols):
    """Build a hashable key for a peel pile row from its group column values.
    
    Returns a tuple of (column_name, value) pairs so the apply function
    can match columns dynamically without positional assumptions.
    """
    return tuple((col, str(row.get(col, ''))) for col in group_cols)
