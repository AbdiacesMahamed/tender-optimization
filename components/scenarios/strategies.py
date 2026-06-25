"""
Scenario strategy implementations — each function takes the working data and
returns (display_data, performance_reallocated, performance_groups_impacted).

Extracted from the monolithic show_detailed_analysis_table() in metrics.py so
each strategy can be debugged, tested, and edited independently.
"""
import logging
import streamlit as st
import pandas as pd
from ..core.utils import (
    get_rate_columns, count_containers, filter_excluded_carrier_facility_rows,
)
from ..reporting.container_tracer import add_detailed_carrier_flips_column
from optimization.performance_logic import allocate_to_highest_performance
from optimization.cascading_logic import build_lockout_mask

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Current Selection
# ---------------------------------------------------------------------------

def apply_current_selection(display_data_with_rates, carrier_col, max_constrained_carriers):
    """Return the data as-is, marking max-constrained carriers for visibility.

    Returns:
        (display_data, reallocated_count, groups_impacted)
    """
    display_data = display_data_with_rates.copy()

    if max_constrained_carriers and len(max_constrained_carriers) > 0:
        max_carrier_names = {mc['carrier'] for mc in max_constrained_carriers}
        if carrier_col in display_data.columns:
            display_data['Carrier'] = display_data[carrier_col].apply(
                lambda x: f"🔒 {x} (MAX)" if x in max_carrier_names else x
            )
            max_constrained_mask = display_data[carrier_col].isin(max_carrier_names)
            if max_constrained_mask.any():
                max_constrained_containers = display_data[max_constrained_mask]['Container Count'].sum()
                st.info(
                    f"🔒 **{len(max_carrier_names)} carriers marked with (MAX)** - "
                    f"{max_constrained_containers:.0f} containers will be reallocated in optimization scenarios"
                )

    if 'Container Numbers' in display_data.columns:
        display_data['Container Count'] = display_data['Container Numbers'].apply(count_containers)

    return display_data, 0, 0


# ---------------------------------------------------------------------------
# Optimized (LP + historical constraints)
# ---------------------------------------------------------------------------

def apply_optimized_strategy(display_data_with_rates, carrier_col,
                             max_constrained_carriers,
                             carrier_facility_exclusions,
                             historical_data_source):
    """Run the cascading LP optimisation and return results.

    Returns:
        (display_data, reallocated_count, groups_impacted)
    """
    from optimization import cascading_allocate_with_constraints

    optimization_source = display_data_with_rates.copy()
    optimization_source = filter_excluded_carrier_facility_rows(
        optimization_source, carrier_facility_exclusions, carrier_col
    )

    cost_weight = st.session_state.get('opt_cost_weight', 70) / 100.0
    performance_weight = st.session_state.get('opt_performance_weight', 30) / 100.0
    max_growth_pct = st.session_state.get('opt_max_growth_pct', 30) / 100.0

    reallocated = 0
    groups_impacted = 0

    try:
        allocated = None
        if len(optimization_source) > 0:
            allocated = cascading_allocate_with_constraints(
                optimization_source,
                max_growth_pct=max_growth_pct,
                cost_weight=cost_weight,
                performance_weight=performance_weight,
                n_historical_weeks=5,
                carrier_column=carrier_col,
                container_column='Container Count',
                excluded_carriers=max_constrained_carriers,
                historical_data=historical_data_source,
            )
    except (ValueError, ImportError) as exc:
        st.warning(f"Unable to build optimized scenario: {exc}")
        return optimization_source, 0, 0

    if allocated is not None and len(allocated) > 0:
        display_data = allocated
    else:
        display_data = optimization_source

    # Calculate how many containers were reallocated/impacted. The optimized
    # output carries one row per carrier per group with that carrier's
    # Historical_Allocation_Pct and its post-optimization Container Count, so the
    # net containers that MOVED is half the sum of |new - historical| container
    # counts per group (each shifted container shows up once as a loss and once
    # as a gain). NOTE: Volume_Change is a label string ("↑ Increase"), NOT a
    # number — parsing it numerically yields all-zeros and a permanently-zero
    # metric, so derive the delta from the percentages against the group total.
    needed = {'Historical_Allocation_Pct', 'New_Allocation_Pct', 'Container Count'}
    group_cols = [col for col in ['Category', 'Lane', 'Week Number'] if col in display_data.columns]
    if needed.issubset(display_data.columns) and group_cols:
        work = display_data.copy()
        work['Container Count'] = pd.to_numeric(work['Container Count'], errors='coerce').fillna(0)
        hist_pct = pd.to_numeric(work['Historical_Allocation_Pct'], errors='coerce').fillna(0)
        new_pct = pd.to_numeric(work['New_Allocation_Pct'], errors='coerce').fillna(0)
        # Group total is the same for every row in a group; rebuild it from the new
        # allocation (new_pct sums to 100% of the group), falling back to the row
        # count when a group's new_pct is degenerate.
        group_totals = work.groupby(group_cols)['Container Count'].transform('sum')
        hist_containers = hist_pct / 100.0 * group_totals
        delta = (work['Container Count'] - hist_containers).abs()
        per_group_moved = (
            delta.groupby([work[c] for c in group_cols]).sum() / 2.0
        )
        reallocated = int(round(per_group_moved.sum()))
        groups_impacted = int((per_group_moved > 0.5).sum())

    return display_data, reallocated, groups_impacted


# ---------------------------------------------------------------------------
# Performance (highest performance carrier)
# ---------------------------------------------------------------------------

def apply_performance_strategy(display_data_with_rates, carrier_col,
                               carrier_facility_exclusions,
                               max_constrained_carriers=None):
    """Reallocate volume to highest-performance carriers.

    Locked-out carriers (0%/max-0 constraints in max_constrained_carriers) are
    barred from being selected as a group's winner, while their containers still
    count toward the group total — matching the Optimized scenario.

    Returns:
        (display_data, reallocated_count, groups_impacted)
    """
    performance_source = display_data_with_rates.copy()
    if carrier_col in performance_source.columns:
        performance_source['Original Carrier'] = performance_source[carrier_col]

    has_lockouts = bool(max_constrained_carriers)

    # Try cached result from calculate_enhanced_metrics. Skip the cache when lockouts
    # are active: the cached allocation was computed without them, so reusing it would
    # silently let a locked-out carrier win the performance pick.
    cached_perf = st.session_state.pop('_cached_perf_allocated', None)
    allocated = None

    if cached_perf is not None and len(cached_perf) > 0 and not has_lockouts:
        allocated = cached_perf
    else:
        perf_input = filter_excluded_carrier_facility_rows(
            performance_source.copy(), carrier_facility_exclusions, carrier_col
        )
        if 'Container Numbers' in perf_input.columns:
            perf_input['Container Count'] = perf_input['Container Numbers'].apply(count_containers)

        lockout_mask = build_lockout_mask(
            perf_input, max_constrained_carriers, carrier_column=carrier_col
        ) if has_lockouts else None

        try:
            allocated = allocate_to_highest_performance(
                perf_input,
                carrier_column=carrier_col,
                container_column='Container Count',
                performance_column='Performance_Score',
                container_numbers_column='Container Numbers',
                excluded_mask=lockout_mask,
            )
        except ValueError as exc:
            st.warning(f"Unable to build performance scenario: {exc}")
            return performance_source, 0, 0

    if allocated is None:
        return performance_source, 0, 0

    # Optimization grouping: [Category, Lane, Week Number] only.
    group_cols = [col for col in ['Category', 'Lane', 'Week Number'] if col in performance_source.columns]
    if not group_cols:
        group_cols = [col for col in ['Week Number'] if col in performance_source.columns]

    # Build reference information so the table shows how volume changed
    original_mix = (
        performance_source.groupby(group_cols)[carrier_col]
        .apply(lambda carriers: ', '.join(sorted({str(v) for v in carriers if pd.notna(v)})))
        .reset_index(name='Original Carrier Mix')
    ) if group_cols else pd.DataFrame(columns=['Original Carrier Mix'])

    original_carrier_totals = (
        performance_source.groupby(group_cols + [carrier_col])['Container Count']
        .sum()
        .reset_index(name='Original Carrier Containers')
    ) if group_cols else pd.DataFrame(columns=['Original Carrier Containers'])

    original_primary = (
        performance_source.sort_values(
            ['Container Count', 'Performance_Score'], ascending=[False, False]
        )
        .groupby(group_cols, as_index=False)
        .first()
    ) if group_cols else pd.DataFrame()

    display_data = allocated.merge(original_mix, on=group_cols, how='left') if not original_mix.empty else allocated
    if not original_carrier_totals.empty:
        display_data = display_data.merge(
            original_carrier_totals, on=group_cols + [carrier_col], how='left'
        )
        display_data['Original Carrier Containers'] = display_data['Original Carrier Containers'].fillna(0)
        display_data['Reallocated Containers'] = (
            display_data['Container Count'] - display_data['Original Carrier Containers']
        )
    else:
        display_data['Original Carrier Containers'] = 0
        display_data['Reallocated Containers'] = display_data['Container Count']

    if not original_primary.empty:
        primary_cols = list(group_cols)
        for col in ['Original Carrier', 'Container Count', 'Performance_Score']:
            if col in original_primary.columns:
                primary_cols.append(col)
        original_primary = original_primary[primary_cols].rename(columns={
            'Original Carrier': 'Original Primary Carrier',
            'Container Count': 'Original Primary Volume',
            'Performance_Score': 'Original Primary Performance',
        })
        display_data = display_data.merge(original_primary, on=group_cols, how='left')

    if 'Original Carrier Containers' in display_data.columns:
        display_data['Original Carrier Containers'] = display_data['Original Carrier Containers'].round(0).astype(int)
    if 'Reallocated Containers' in display_data.columns:
        display_data['Reallocated Containers'] = display_data['Reallocated Containers'].round(0).astype(int)

    reallocated = 0
    groups_impacted = 0
    if 'Reallocated Containers' in display_data.columns:
        reallocated = int(display_data['Reallocated Containers'].sum())
        if group_cols:
            groups_impacted = int(
                display_data.loc[display_data['Reallocated Containers'] > 0, group_cols]
                .drop_duplicates()
                .shape[0]
            )
        elif reallocated:
            groups_impacted = 1

    if 'Original Primary Carrier' in display_data.columns and carrier_col in display_data.columns:
        display_data['Carrier Change'] = (
            display_data[carrier_col].astype(str)
            + ' ← '
            + display_data['Original Primary Carrier'].fillna('N/A').astype(str)
        )

    return display_data, reallocated, groups_impacted


# ---------------------------------------------------------------------------
# Cheapest Cost
# ---------------------------------------------------------------------------

def apply_cheapest_strategy(source_data, carrier_col, carrier_facility_exclusions,
                            has_constraints, constrained_data, metrics,
                            final_filtered_data, unconstrained_data,
                            max_constrained_carriers=None):
    """Find the cheapest carrier per lane/week/category.

    Locked-out carriers (0%/max-0 constraints in max_constrained_carriers) cannot
    be picked as a group's cheapest carrier, while their containers still count
    toward the group total — matching the Optimized scenario.

    Unlike the other strategies this branch builds its own column set and
    description, so it returns a richer tuple:

    Returns:
        (display_data, download_data, desc, filename, rate_cols)
    """
    rate_cols = get_rate_columns()

    source_data = filter_excluded_carrier_facility_rows(source_data, carrier_facility_exclusions, carrier_col)

    if 'Container Numbers' in source_data.columns:
        source_data['Container Count'] = source_data['Container Numbers'].apply(count_containers)

    if rate_cols['rate'] in source_data.columns:
        source_data[rate_cols['rate']] = pd.to_numeric(source_data[rate_cols['rate']], errors='coerce')

    if len(source_data) == 0:
        st.warning("⚠️ No carriers with valid rates found for cheapest cost analysis.")
        return pd.DataFrame(), pd.DataFrame(), "", "", rate_cols

    group_cols = [col for col in ['Category', 'Lane', 'Week Number'] if col in source_data.columns]

    if not group_cols:
        st.warning("⚠️ No grouping columns (Category, Week Number, Lane) found in data.")
        return source_data.copy(), source_data.copy(), "", "", rate_cols

    working = source_data.copy()
    working['Container Count'] = pd.to_numeric(working['Container Count'], errors='coerce').fillna(0)
    working['_rate_sort'] = working[rate_cols['rate']].fillna(float('inf'))
    working['_carrier_sort'] = working[carrier_col].astype(str)

    # Lockout: locked-out carriers sort last so the per-group .first() never picks
    # them, but their rows stay in `working` so the group's container total (summed
    # below) still includes their volume — it just gets reassigned to an allowed
    # carrier. If every carrier in a group is locked, the group keeps its cheapest
    # locked carrier rather than disappearing.
    sort_keys = ['_rate_sort', '_carrier_sort']
    sort_asc = [True, True]
    if max_constrained_carriers:
        working['_lockout_sort'] = build_lockout_mask(
            working, max_constrained_carriers, carrier_column=carrier_col
        ).astype(int)
        sort_keys.insert(0, '_lockout_sort')  # 0 (allowed) before 1 (locked)
        sort_asc.insert(0, True)

    working = working.sort_values(sort_keys, ascending=sort_asc)

    cheapest_per_group = working.groupby(group_cols, as_index=False).first()

    container_totals = (
        working.groupby(group_cols, as_index=False)['Container Count']
        .sum()
        .rename(columns={'Container Count': '_total_containers'})
    )

    if 'Container Numbers' in working.columns:
        def _concat_dedupe(values):
            all_containers = []
            for v in values:
                if pd.notna(v) and str(v).strip():
                    all_containers.extend([c.strip() for c in str(v).split(',') if c.strip()])
            unique_containers = list(dict.fromkeys(all_containers))
            return ', '.join(unique_containers)

        container_numbers = (
            working.groupby(group_cols)['Container Numbers']
            .apply(_concat_dedupe)
            .reset_index(name='_container_numbers')
        )
        cheapest_per_group = cheapest_per_group.merge(container_numbers, on=group_cols, how='left')
        cheapest_per_group['Container Numbers'] = cheapest_per_group['_container_numbers'].fillna('')
        cheapest_per_group['_actual_container_count'] = cheapest_per_group['Container Numbers'].apply(count_containers)

    cheapest_per_group = cheapest_per_group.merge(container_totals, on=group_cols, how='left')

    if 'Container Numbers' in working.columns and '_actual_container_count' in cheapest_per_group.columns:
        cheapest_per_group['Container Count'] = cheapest_per_group['_actual_container_count']
    else:
        cheapest_per_group['Container Count'] = cheapest_per_group['_total_containers'].fillna(0)

    cheapest_per_group['Total Cost'] = (
        cheapest_per_group[rate_cols['rate']].fillna(0) * cheapest_per_group['Container Count']
    )

    current_cost_per_group = working.groupby(group_cols)[rate_cols['total_rate']].sum().reset_index()
    current_cost_per_group = current_cost_per_group.rename(columns={rate_cols['total_rate']: '_current_total_cost'})
    cheapest_per_group = cheapest_per_group.merge(current_cost_per_group, on=group_cols, how='left')

    cheapest_per_group['Potential Savings'] = (
        cheapest_per_group['_current_total_cost'].fillna(0) - cheapest_per_group['Total Cost']
    )
    cheapest_per_group['Savings Percentage'] = cheapest_per_group.apply(
        lambda row: (row['Potential Savings'] / row['_current_total_cost'] * 100)
        if row['_current_total_cost'] > 0 else 0,
        axis=1,
    )

    # Clean up helper columns
    for col in ['_rate_sort', '_carrier_sort', '_lockout_sort', '_total_containers',
                '_container_numbers', '_current_total_cost', '_actual_container_count', '_summed_count']:
        if col in cheapest_per_group.columns:
            cheapest_per_group.drop(columns=col, inplace=True)

    display_data = cheapest_per_group

    # Column selection
    cols = list(group_cols)
    cols.insert(0, carrier_col)
    if 'Ocean ETA' in display_data.columns:
        cols.append('Ocean ETA')
    if 'Container Numbers' in display_data.columns:
        cols.append('Container Numbers')
    cols.extend(['Container Count', rate_cols['rate'], 'Total Cost', 'Potential Savings', 'Savings Percentage'])
    if 'Missing_Rate' in display_data.columns:
        cols.append('Missing_Rate')

    download_data = display_data.copy()
    display_data = display_data[[c for c in cols if c in display_data.columns]].copy()

    # Carrier Flips
    cheapest_baseline = unconstrained_data.copy() if has_constraints else final_filtered_data.copy()
    display_data = add_detailed_carrier_flips_column(display_data, cheapest_baseline, carrier_col=carrier_col)
    download_data = add_detailed_carrier_flips_column(download_data, cheapest_baseline, carrier_col=carrier_col)
    for df in (display_data, download_data):
        if 'Carrier Flips (Detailed)' in df.columns:
            df.rename(columns={'Carrier Flips (Detailed)': 'Carrier Flips'}, inplace=True)

    rename_map = {
        'Savings Percentage': 'Savings %',
        carrier_col: 'NEW SCAC',
        'Missing_Rate': '⚠️ No Rate',
    }
    display_data = display_data.rename(columns=rename_map).sort_values('Potential Savings', ascending=False)
    download_data = download_data.rename(columns=rename_map)

    # Cost summary
    cheapest_cost = display_data['Total Cost'].sum() if 'Total Cost' in display_data.columns else 0
    if has_constraints:
        constrained_cost = constrained_data[rate_cols['total_rate']].sum()
        total_cost = constrained_cost + cheapest_cost
        cost_breakdown = f" (Constrained: ${constrained_cost:,.2f} + Unconstrained: ${cheapest_cost:,.2f})"
    else:
        total_cost = cheapest_cost
        cost_breakdown = ""

    rate_type_label = st.session_state.get('rate_type', 'Base Rate')
    desc = f"💰 Cheapest carrier per lane/week/category ({rate_type_label}) - Total: ${total_cost:,.2f}{cost_breakdown}"
    filename = 'cheapest_cost.csv'

    return display_data, download_data, desc, filename, rate_cols
