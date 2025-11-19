"""
Container-level tracing to track exact movements between carriers.

This module enables precise tracking of which specific containers moved
from which carrier to which carrier, with full historical context.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional


def parse_container_ids(container_str):
    """
    Parse comma-separated container IDs from string.
    
    Parameters:
    -----------
    container_str : str
        Comma-separated container IDs (e.g., "MSDU123, TCKU456, MSNU789")
        
    Returns:
    --------
    list
        List of individual container IDs
    """
    if pd.isna(container_str) or container_str == '':
        return []
    return [cid.strip() for cid in str(container_str).split(',') if cid.strip()]


def build_container_origin_map(original_data, carrier_col='Dray SCAC(FL)', week_col='Week Number'):
    """
    Build a comprehensive map of which carrier originally had each container.
    
    For each container ID, records:
    - Original carrier
    - Week number
    - Port, Lane, Facility, Terminal, Category (full context)
    
    Parameters:
    -----------
    original_data : pd.DataFrame
        Original baseline data (Current Selection)
    carrier_col : str
        Column name for carrier identification
    week_col : str
        Column name for week number
        
    Returns:
    --------
    dict
        {container_id: {
            'original_carrier': str,
            'week': int,
            'port': str,
            'lane': str,
            'facility': str,
            'terminal': str,
            'category': str
        }}
    """
    container_map = {}
    
    context_cols = {
        'discharged_port': 'Discharged Port',
        'lane': 'Lane',
        'facility': 'Facility',
        'terminal': 'Terminal',
        'category': 'Category',
        'week_number': 'Week Number'
    }
    
    for _, row in original_data.iterrows():
        carrier = row.get(carrier_col, 'Unknown')
        week = row.get(week_col, 0)
        container_str = row.get('Container Numbers', '')
        
        # Parse all container IDs from this row
        container_ids = parse_container_ids(container_str)
        
        # Build context for each container
        context = {
            'original_carrier': carrier,
            'week': int(week) if pd.notna(week) else 0
        }
        
        # Add location context with standardized keys
        for key, col_name in context_cols.items():
            if col_name in row.index:
                context[key] = row[col_name] if pd.notna(row[col_name]) else ''
            else:
                context[key] = ''
        
        # Map each container to its origin
        for container_id in container_ids:
            if container_id not in container_map:
                container_map[container_id] = context
            else:
                # Container appears multiple times - this shouldn't happen
                # Keep first occurrence but flag it
                if container_map[container_id].get('duplicate'):
                    container_map[container_id]['duplicate_count'] = container_map[container_id].get('duplicate_count', 1) + 1
                else:
                    container_map[container_id]['duplicate'] = True
                    container_map[container_id]['duplicate_count'] = 2
    
    return container_map


def trace_container_movements(current_data, origin_map, carrier_col='Dray SCAC(FL)', group_cols=None):
    """
    Trace which containers moved from which carriers.
    
    For each row in current data, identifies:
    - Which containers came from the same carrier (kept)
    - Which containers came from different carriers (flipped)
    - Details of source carriers for flipped containers
    - Original count for this carrier IN THIS SPECIFIC GROUP (for display)
    
    Parameters:
    -----------
    current_data : pd.DataFrame
        Current scenario data
    origin_map : dict
        Container origin map from build_container_origin_map()
    carrier_col : str
        Column name for carrier identification
    group_cols : list
        Grouping columns to determine per-group original counts
        
    Returns:
    --------
    list of dict
        For each row: {
            'kept_containers': [(container_id, ...), ...],
            'flipped_containers': [(container_id, from_carrier), ...],
            'unknown_containers': [container_id, ...],
            'flip_summary': {from_carrier: count, ...},
            'original_count': int (how many this carrier had originally IN THIS GROUP)
        }
    """
    trace_results = []
    
    # Default group columns if not provided
    if group_cols is None:
        group_cols = ['Discharged Port', 'Lane', 'Facility', 'Week Number']
        if 'Category' in current_data.columns:
            group_cols.insert(0, 'Category')
        if 'Terminal' in current_data.columns:
            group_cols.append('Terminal')
        group_cols = [col for col in group_cols if col in current_data.columns]
    
    # Build original state PER GROUP: {group_key: {carrier: [container_ids]}}
    original_group_state = {}
    
    # Map column names to standardized keys
    col_to_key = {
        'Discharged Port': 'discharged_port',
        'Lane': 'lane',
        'Facility': 'facility',
        'Terminal': 'terminal',
        'Category': 'category',
        'Week Number': 'week_number'
    }
    
    for container_id, info in origin_map.items():
        # Build group key from container's origin info using standardized keys
        group_key_values = []
        for col in group_cols:
            key = col_to_key.get(col, col.lower().replace(' ', '_'))
            value = info.get(key, '')
            # Handle week number specially
            if col == 'Week Number' and key == 'week':
                value = info.get('week', '')
            group_key_values.append(value)
        
        group_key = tuple(group_key_values)
        orig_carrier = info['original_carrier']
        
        if group_key not in original_group_state:
            original_group_state[group_key] = {}
        if orig_carrier not in original_group_state[group_key]:
            original_group_state[group_key][orig_carrier] = []
        
        original_group_state[group_key][orig_carrier].append(container_id)
    
    for _, row in current_data.iterrows():
        current_carrier = row.get(carrier_col, 'Unknown')
        container_str = row.get('Container Numbers', '')
        container_ids = parse_container_ids(container_str)
        
        # Build group key for this row
        group_key = tuple(row.get(col, '') for col in group_cols)
        
        # Get original count for THIS carrier IN THIS GROUP
        original_count_in_group = 0
        if group_key in original_group_state and current_carrier in original_group_state[group_key]:
            original_count_in_group = len(original_group_state[group_key][current_carrier])
        
        kept = []
        flipped = []
        unknown = []
        flip_summary = {}
        
        for container_id in container_ids:
            if container_id not in origin_map:
                # New container (shouldn't happen normally)
                unknown.append(container_id)
            else:
                origin = origin_map[container_id]
                orig_carrier = origin['original_carrier']
                
                if orig_carrier == current_carrier:
                    # Container stayed with same carrier
                    kept.append(container_id)
                else:
                    # Container moved from different carrier
                    flipped.append((container_id, orig_carrier))
                    flip_summary[orig_carrier] = flip_summary.get(orig_carrier, 0) + 1
        
        trace_results.append({
            'kept_containers': kept,
            'flipped_containers': flipped,
            'unknown_containers': unknown,
            'flip_summary': flip_summary,
            'flip_containers_by_source': {carrier: [cid for cid, c in flipped if c == carrier] for carrier in flip_summary.keys()},  # NEW: containers grouped by source carrier
            'total_kept': len(kept),
            'total_flipped': len(flipped),
            'total_unknown': len(unknown),
            'original_count': original_count_in_group,  # PER-GROUP count
            'current_count': len(container_ids),
            'all_original_containers': original_group_state.get(group_key, {}).get(current_carrier, []) if group_key in original_group_state else []  # NEW: original container IDs
        })
    
    return trace_results


def format_flip_details(trace_result, show_container_ids=True, max_carriers=5):
    """
    Format traced container movements into readable text with container IDs.
    
    Format: Had X [container IDs] → From CARRIER (+Y) [container IDs], Lost Z [container IDs] → Now Total
    
    Parameters:
    -----------
    trace_result : dict
        Single trace result from trace_container_movements()
    show_container_ids : bool
        Whether to include actual container IDs in output (default True)
    max_carriers : int
        Maximum number of source carriers to show individually
        
    Returns:
    --------
    str
        Formatted flip description with container IDs
    """
    kept_count = trace_result['total_kept']
    flipped_count = trace_result['total_flipped']
    unknown_count = trace_result['total_unknown']
    flip_summary = trace_result['flip_summary']
    original_count = trace_result.get('original_count', 0)
    current_count = trace_result.get('current_count', kept_count + flipped_count + unknown_count)
    
    # Container ID lists
    kept_containers = trace_result.get('kept_containers', [])
    all_original_containers = trace_result.get('all_original_containers', [])
    flip_containers_by_source = trace_result.get('flip_containers_by_source', {})
    flipped_containers = trace_result.get('flipped_containers', [])
    
    # Calculate lost containers (originally had but not in kept)
    lost_containers = []
    if all_original_containers:
        lost_containers = [cid for cid in all_original_containers if cid not in kept_containers]
    lost_count = len(lost_containers)
    
    # Build the display string
    parts = []
    
    # Part 1: Show what carrier started with (Had X)
    if original_count > 0:
        if show_container_ids and all_original_containers:
            container_list = ', '.join(all_original_containers[:3])
            if len(all_original_containers) > 3:
                container_list += f"... ({original_count} total)"
            parts.append(f"Had {original_count} [{container_list}]")
        else:
            parts.append(f"Had {original_count}")
    else:
        parts.append("Had 0")
    
    # Part 2: Show changes
    # "kept all" means: original_count == current_count AND all current are kept (no flips/unknown)
    if original_count > 0 and original_count == current_count and kept_count == current_count and flipped_count == 0 and unknown_count == 0:
        # Kept everything, no changes
        parts.append("(kept all)")
    else:
        changes = []
        
        # Gains from other carriers
        if flipped_count > 0:
            sorted_flips = sorted(flip_summary.items(), key=lambda x: x[1], reverse=True)
            
            if show_container_ids:
                # Show with container IDs
                if len(sorted_flips) == 1:
                    carrier, count = sorted_flips[0]
                    containers = flip_containers_by_source.get(carrier, [])
                    container_list = ', '.join(containers[:2])
                    if len(containers) > 2:
                        container_list += f"... ({count} total)"
                    changes.append(f"From {carrier} (+{count}) [{container_list}]")
                elif len(sorted_flips) <= max_carriers:
                    flip_parts = []
                    for carrier, count in sorted_flips:
                        containers = flip_containers_by_source.get(carrier, [])
                        container_list = ', '.join(containers[:2])
                        if len(containers) > 2:
                            container_list += f"..."
                        flip_parts.append(f"{carrier} (+{count}) [{container_list}]")
                    changes.append(f"From {' + '.join(flip_parts)}")
                else:
                    # Too many carriers - show top ones
                    flip_parts = []
                    for carrier, count in sorted_flips[:max_carriers]:
                        containers = flip_containers_by_source.get(carrier, [])
                        container_list = ', '.join(containers[:2])
                        if len(containers) > 2:
                            container_list += f"..."
                        flip_parts.append(f"{carrier} (+{count}) [{container_list}]")
                    
                    remaining_count = sum(count for _, count in sorted_flips[max_carriers:])
                    remaining_carriers = len(sorted_flips) - max_carriers
                    flip_parts.append(f"{remaining_carriers} others (+{remaining_count})")
                    changes.append(f"From {' + '.join(flip_parts)}")
            else:
                # Show without container IDs
                if len(sorted_flips) == 1:
                    carrier, count = sorted_flips[0]
                    changes.append(f"From {carrier} (+{count})")
                elif len(sorted_flips) <= max_carriers:
                    flip_strs = [f"{carrier} (+{count})" for carrier, count in sorted_flips]
                    changes.append(f"From {' + '.join(flip_strs)}")
                else:
                    top_flips = sorted_flips[:max_carriers]
                    remaining_count = sum(count for _, count in sorted_flips[max_carriers:])
                    remaining_carriers = len(sorted_flips) - max_carriers
                    
                    flip_strs = [f"{carrier} (+{count})" for carrier, count in top_flips]
                    flip_strs.append(f"{remaining_carriers} others (+{remaining_count})")
                    changes.append(f"From {' + '.join(flip_strs)}")
        
        # Losses (if original > kept)
        if lost_count > 0:
            if show_container_ids and lost_containers:
                container_list = ', '.join(lost_containers[:2])
                if len(lost_containers) > 2:
                    container_list += f"... ({lost_count} total)"
                changes.append(f"Lost {lost_count} [{container_list}]")
            else:
                changes.append(f"Lost {lost_count}")
        
        # Unknown/new containers
        if unknown_count > 0:
            changes.append(f"New ({unknown_count})")
        
        if changes:
            parts.append(" → " + ", ".join(changes))
    
    # Part 3: Show final count (no container IDs for "Now" as requested)
    parts.append(f"→ Now {current_count}")
    
    return " ".join(parts)


def add_detailed_carrier_flips_column(current_data, original_data, 
                                     carrier_col='Dray SCAC(FL)',
                                     show_container_ids=True):
    """
    Add detailed carrier flips column with exact container tracing.
    
    This is the ACCURATE version that traces individual containers
    from their original carrier to their current carrier.
    
    Parameters:
    -----------
    current_data : pd.DataFrame
        Current scenario data
    original_data : pd.DataFrame
        Original baseline data (Current Selection)
    carrier_col : str
        Column name for carrier identification
    show_container_ids : bool
        Whether to show actual container IDs in display
        
    Returns:
    --------
    pd.DataFrame
        Data with added 'Carrier Flips (Detailed)' column
    """
    if original_data is None or original_data.empty:
        current_data['Carrier Flips (Detailed)'] = 'No baseline'
        return current_data
    
    if 'Container Numbers' not in original_data.columns:
        current_data['Carrier Flips (Detailed)'] = 'No container tracking'
        return current_data
    
    # Step 1: Build origin map
    origin_map = build_container_origin_map(original_data, carrier_col)
    
    # Step 2: Trace movements
    trace_results = trace_container_movements(current_data, origin_map, carrier_col)
    
    # Step 3: Format results
    flip_details = [format_flip_details(result, show_container_ids) for result in trace_results]
    
    current_data['Carrier Flips (Detailed)'] = flip_details
    
    return current_data


def get_container_movement_summary(current_data, original_data, carrier_col='Dray SCAC(FL)'):
    """
    Get summary statistics of container movements.
    
    Returns overall metrics like:
    - Total containers that stayed with original carrier
    - Total containers that flipped
    - Top carrier-to-carrier flows
    
    Parameters:
    -----------
    current_data : pd.DataFrame
        Current scenario data
    original_data : pd.DataFrame
        Original baseline data
    carrier_col : str
        Column name for carrier identification
        
    Returns:
    --------
    dict
        Summary statistics
    """
    if original_data is None or original_data.empty:
        return {'error': 'No baseline data'}
    
    if 'Container Numbers' not in original_data.columns:
        return {'error': 'No container tracking'}
    
    # Build origin map
    origin_map = build_container_origin_map(original_data, carrier_col)
    
    # Trace movements
    trace_results = trace_container_movements(current_data, origin_map, carrier_col)
    
    # Aggregate statistics
    total_kept = sum(r['total_kept'] for r in trace_results)
    total_flipped = sum(r['total_flipped'] for r in trace_results)
    total_unknown = sum(r['total_unknown'] for r in trace_results)
    
    # Build flow matrix: from_carrier -> to_carrier -> count
    flows = {}
    for idx, result in enumerate(trace_results):
        to_carrier = current_data.iloc[idx].get(carrier_col, 'Unknown')
        
        for from_carrier, count in result['flip_summary'].items():
            if from_carrier not in flows:
                flows[from_carrier] = {}
            flows[from_carrier][to_carrier] = flows[from_carrier].get(to_carrier, 0) + count
    
    # Get top flows
    all_flows = []
    for from_carrier, to_carriers in flows.items():
        for to_carrier, count in to_carriers.items():
            all_flows.append((from_carrier, to_carrier, count))
    
    top_flows = sorted(all_flows, key=lambda x: x[2], reverse=True)[:10]
    
    return {
        'total_containers': total_kept + total_flipped + total_unknown,
        'total_kept': total_kept,
        'total_flipped': total_flipped,
        'total_unknown': total_unknown,
        'kept_percentage': (total_kept / (total_kept + total_flipped + total_unknown) * 100) if (total_kept + total_flipped + total_unknown) > 0 else 0,
        'flipped_percentage': (total_flipped / (total_kept + total_flipped + total_unknown) * 100) if (total_kept + total_flipped + total_unknown) > 0 else 0,
        'top_flows': top_flows,
        'unique_source_carriers': len(flows),
        'unique_destination_carriers': len(set(to for _, to, _ in all_flows))
    }
