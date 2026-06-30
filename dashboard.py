"""
Carrier Tender Optimization Dashboard
Main application file that orchestrates all components
"""

# Import necessary libraries
import logging
import pandas as pd
import streamlit as st

# Module logger. Used by the isolated render guards around the bottom analysis
# panels (see show_historic_volume_analysis / show_carrier_flip_report below).
logger = logging.getLogger(__name__)

# Import diagnostic tool


# Import all dashboard components
from components import (
    # Configuration
    configure_page, apply_custom_css, show_header,
    
    # Data handling
    show_file_upload_section, load_data_files, process_performance_data,
    validate_and_process_gvt_data, validate_and_process_rate_data, merge_all_data, 
    apply_volume_weighted_performance, create_comprehensive_data,perform_lane_analysis,
    
    # Filtering
    show_filter_interface, apply_filters_to_data, show_selection_summary,
    show_rate_type_selector,
    
    # Metrics
    calculate_enhanced_metrics, display_current_metrics, show_detailed_analysis_table,
    show_top_savings_opportunities, show_complete_data_export, show_performance_score_analysis,
    show_carrier_performance_matrix,
    apply_peel_pile_as_constraints,
    
    # Tables and analysis
    show_summary_tables,
    
    # Analytics and visualizations
    show_advanced_analytics, show_interactive_visualizations,
    
    # Utilities
    show_calculation_logic, show_debug_performance_merge, show_footer,
    show_performance_assignments_table, export_performance_assignments,
    deduplicate_containers_per_lane_week
)

from components.constraints.processor import (
    process_constraints_file,
    apply_constraints_to_data,
    show_constraints_summary,
)

from components.reporting.carrier_flip import show_carrier_flip_report

# JBH Allocation Model — runs the JB Hunt allocation rules (config-driven per
# port) on an Inbound Container Milestone file. Self-contained: own uploader,
# no dependency on the tender-optimization data flow.
# TEMPORARILY HIDDEN — re-enable alongside the show_jbh_allocation_report call below.
# from optimization.jbh_allocation.ui import show_jbh_allocation_report

# AI assistant (Bedrock-powered chatbot for analysis + constraint generation)
from components.chatbot import show_chatbot_sidebar, get_applied_constraints_df

# Import optimization module for historic volume analysis
from optimization import show_historic_volume_analysis

def main():
    """Main dashboard application"""
    
    # Configure page and apply styling
    configure_page()
    apply_custom_css()
    show_header()
    
    # File upload and data loading
    gvt_file, rate_file, performance_file, constraints_file = show_file_upload_section()
    
    with st.spinner('⚙️ Loading and processing data...'):
        GVTdata, Ratedata, Performancedata, has_performance = load_data_files(gvt_file, rate_file, performance_file)
        
        # Process performance data
        performance_clean, has_performance = process_performance_data(Performancedata, has_performance)
        
        # Validate and process data. A ValueError here means the file in a given
        # upload slot is missing the columns that identify it (e.g. a Rate sheet
        # dropped into the GVT slot). Surface a plain "wrong file" message naming
        # the section instead of letting the raw traceback reach the user.
        try:
            GVTdata = validate_and_process_gvt_data(GVTdata)
        except ValueError:
            st.error(
                "❌ The file in the **GVT Data** section doesn't look like GVT data. "
                "Please check that you uploaded the correct file in that section "
                "(it may be a Rate, Performance, or Constraints file by mistake)."
            )
            st.stop()

        try:
            Ratedata = validate_and_process_rate_data(Ratedata)
        except ValueError:
            st.error(
                "❌ The file in the **Rate Data** section doesn't look like rate data. "
                "Please check that you uploaded the correct file in that section "
                "(it may be a GVT, Performance, or Constraints file by mistake)."
            )
            st.stop()

        # Merge all data (this already calls apply_volume_weighted_performance internally)
        merged_data = merge_all_data(GVTdata, Ratedata, performance_clean, has_performance)

    # Report future-dated Closed containers removed during GVT processing.
    # Mirrors the deduplication notice below: state the count and why.
    closed_future_removed = st.session_state.get('closed_future_removed', 0)
    if closed_future_removed > 0:
        cutoff = st.session_state.get('closed_future_cutoff', 'today')
        st.info(
            f"ℹ️ **Closed Container Removal:** Removed {closed_future_removed:,} container(s) marked "
            f"**Closed** with an Ocean ETA after {cutoff}. A container can't be closed before it has "
            f"arrived, so these future-dated closed records are excluded from the analysis."
        )
    
    # Show performance assignments table
    show_performance_assignments_table()
    
    with st.spinner('📊 Creating comprehensive data view...'):
        comprehensive_data = create_comprehensive_data(merged_data)

    # AI assistant sidebar — analyzes the loaded data, prices carrier flips, and
    # proposes/applies constraints. Pass the rate sheet so flip-cost simulation can
    # price moves to carriers not currently on a lane. Pass the uploaded constraint
    # file so the assistant edits the user's actual constraints. rate_type defaults
    # from the selector's session-state value (set on the previous run).
    show_chatbot_sidebar(comprehensive_data, rate_data=Ratedata,
                         constraints_file=constraints_file)

    # Show rate type selector (Base Rate vs CPC)
    show_rate_type_selector(comprehensive_data)
    
    # Show filters
    show_filter_interface(comprehensive_data)
    
    # Apply filters
    final_filtered_data, display_ports, display_fcs, display_weeks, display_scacs = apply_filters_to_data(comprehensive_data)
    
    # Show selection summary
    show_selection_summary(display_ports, display_fcs, display_weeks, display_scacs, final_filtered_data)
    
    # Process and apply constraints if file is uploaded
    with st.spinner('🔒 Processing constraints...'):
        constraints_df = None
        constrained_data = pd.DataFrame()
        unconstrained_data = final_filtered_data.copy()
        constraint_summary = []
        max_constrained_carriers = []  # Carriers with maximum constraints (scoped)
        carrier_facility_exclusions = {}  # Carrier+facility exclusions
        
        explanation_logs = []  # For downloadable constraint explanations

        # The assistant seeds the uploaded constraint file into its working set, so
        # when the user clicks "Apply" in the chat panel the applied set ALREADY
        # contains the uploaded rows plus any edits/additions. In that case the
        # applied set is authoritative — use it alone and do NOT also re-process the
        # raw file (that would double-count the uploaded rows). Only fall back to the
        # raw uploaded file when the user hasn't applied anything through the chat.
        ai_constraints_df = get_applied_constraints_df()
        if ai_constraints_df is not None and len(ai_constraints_df) > 0:
            constraints_df = ai_constraints_df.sort_values(
                'Priority Score', ascending=False, na_position='last'
            )
            st.markdown("---")
            st.info(f"🤖 Applying {len(ai_constraints_df)} constraint(s) from the AI assistant "
                    "(includes any uploaded rows it incorporated).")
        elif constraints_file is not None:
            st.markdown("---")
            constraints_df = process_constraints_file(constraints_file)

        # Merge the always-on prebuilt per-port constraints to the FRONT of the
        # frame so they are applied before (and cannot be overwritten by) any
        # uploaded/chatbot rule's Priority Score. Toggled in code only
        # (components/constraints/prebuilt.py) — never surfaced in the UI.
        from components.constraints.prebuilt import (
            merge_prebuilt_first, load_prebuilt_constraints, load_pnw_generated_constraints,
        )
        _prebuilt_count = len(load_prebuilt_constraints())
        _pnw_count = len(load_pnw_generated_constraints(final_filtered_data))
        # Pass the filtered data so the data-derived PNW vessel rules (Hunt 130/week,
        # 60-per-vessel cap) are generated and merged into the always-on front block.
        constraints_df = merge_prebuilt_first(constraints_df, final_filtered_data)
        if _prebuilt_count > 0 or _pnw_count > 0:
            st.markdown("---")
            st.success(f"🔒 Applied {_prebuilt_count + _pnw_count} standing port constraint(s) "
                       f"({_prebuilt_count} port lockout(s), {_pnw_count} PNW vessel rule(s)) "
                       "— these take precedence and are always enforced.")

        if constraints_df is not None and len(constraints_df) > 0:
            # Apply constraints to filtered data
            # Pass Ratedata so we can find capable carriers for lanes when reallocation is needed
            constrained_data, unconstrained_data, constraint_summary, max_constrained_carriers, carrier_facility_exclusions, explanation_logs = apply_constraints_to_data(
                final_filtered_data, constraints_df, Ratedata
            )

            # Show constraint summary
            if len(constraint_summary) > 0:
                show_constraints_summary(constraint_summary, explanation_logs)

            # PNW post-allocation safety nets, applied across the COMBINED constrained +
            # unconstrained tables (the rules bind on a carrier's TOTAL PNW volume, not
            # within either table alone):
            #   * Rule 2 — no SCAC over 60 containers on a vessel. The generated Max-60
            #     rows bind during allocation, but the scenario optimizer can move a
            #     carrier ONTO a vessel afterward; this trims any such over-cap excess.
            #   * Rules 3 & 4 — one vessel per carrier among same-day arrivals.
            # Both clear the displaced/over-cap carrier so the optimizer re-homes them.
            from components.constraints.pnw_vessel_rules import (
                enforce_per_vessel_cap_across, enforce_one_vessel_per_carrier_across,
            )
            constrained_data, unconstrained_data, _cap_chg = enforce_per_vessel_cap_across(
                constrained_data, unconstrained_data)
            constrained_data, unconstrained_data, _ov_chg = enforce_one_vessel_per_carrier_across(
                constrained_data, unconstrained_data)
            if _cap_chg:
                _capped = sum(c['containers'] for c in _cap_chg)
                st.info(
                    f"🚢 PNW per-vessel cap released {_capped} container(s) over the "
                    f"{60}-per-vessel limit across {len(_cap_chg)} (vessel, carrier) group(s)."
                )
            if _ov_chg:
                _moved = sum(c['containers'] for c in _ov_chg)
                st.info(
                    f"🚢 PNW one-vessel-per-carrier rule released {_moved} container(s) "
                    f"across {len(_ov_chg)} carrier/vessel split(s) so each carrier "
                    "draws from a single vessel among same-day arrivals."
                )
        elif constraints_file is not None:
            st.warning("⚠️ Constraints file could not be processed")
        else:
            st.info("ℹ️ No constraints file uploaded - all data is unconstrained")

    # ==================== PEEL PILE CONSTRAINTS ====================
    # Apply peel pile allocations as constraints (from session state)
    # This must happen after constraint file processing but before metrics calculation
    if st.session_state.get('peel_pile_allocations'):
        # Build the scoped-max ceilings from any uploaded file constraints so the peel
        # pile honors the SAME caps (e.g. a file rule "RKNE max 40 on VIENNA EXPRESS"
        # must not be busted by peel-pile-assigning that vessel to RKNE). Ceilings are
        # indexed against unconstrained_data (the rows peel pile can still move) and
        # pre-credited with whatever the file pass already locked into constrained_data.
        from components.constraints.processor import compute_scoped_max_ceilings, credit_ceilings
        pp_ceilings = []
        if constraints_df is not None and len(constraints_df) > 0:
            pp_ceilings = compute_scoped_max_ceilings(constraints_df, unconstrained_data)
            # Pre-credit caps with file-constrained volume already assigned to the carrier.
            if len(constrained_data) > 0:
                _cc = 'Dray SCAC(FL)' if 'Dray SCAC(FL)' in constrained_data.columns else 'Carrier'
                for c in pp_ceilings:
                    locked = constrained_data[
                        constrained_data[_cc].astype(str).str.strip().str.upper()
                        == str(c['carrier']).strip().upper()
                    ]
                    if len(locked):
                        c['allocated'] += int(locked['Container Count'].sum())

        constrained_data, unconstrained_data, constraint_summary, peel_pile_carriers = apply_peel_pile_as_constraints(
            final_filtered_data, constrained_data, unconstrained_data, constraint_summary,
            scoped_max_ceilings=pp_ceilings,
        )
        # Add peel pile carriers to the max_constrained list so optimization doesn't reassign them
        # Peel pile carriers are global (no scope filters)
        for pp_carrier in peel_pile_carriers:
            max_constrained_carriers.append({'carrier': pp_carrier})

    # Expose the (now final) Applied Constraints Summary to the AI assistant so its
    # read_constraints_summary tool can explain constraint impact and ground new
    # suggestions. Written each run after file + peel-pile constraints are applied;
    # the sidebar reads it on the next user message. Empty list when nothing applied.
    st.session_state['chatbot_constraint_summary'] = constraint_summary

    # ==================== DEDUPLICATE CONTAINERS ====================
    # A container can only belong to ONE carrier per lane/week (zero sum).
    # Apply dedup before metrics so cost cards and detailed table use the same data.
    raw_container_count = int(final_filtered_data['Container Count'].sum())
    final_filtered_data = deduplicate_containers_per_lane_week(final_filtered_data)
    deduped_container_count = int(final_filtered_data['Container Count'].sum())
    dedup_removed = raw_container_count - deduped_container_count
    if dedup_removed > 0:
        st.info(
            f"ℹ️ **Container Deduplication:** Reporting {deduped_container_count:,} unique containers "
            f"(raw data has {raw_container_count:,} rows — {dedup_removed} duplicate container(s) removed). "
            f"Duplicates occur when the same container appears under multiple carriers or rows in the same "
            f"lane/week. Each physical container is counted only once, assigned to the first carrier encountered."
        )
    if len(constrained_data) > 0:
        constrained_data = deduplicate_containers_per_lane_week(constrained_data)
    unconstrained_data = deduplicate_containers_per_lane_week(unconstrained_data)
    
    # Calculate metrics on the FULL filtered data (before constraint split)
    # Pass unconstrained_data so scenarios (Performance, Cheapest, Optimized) 
    # only run on unconstrained containers when constraints are active
    # Pass max_constrained_carriers so optimization knows which carriers have hard caps
    # Pass carrier_facility_exclusions so scenarios respect facility-level exclusions
    # Pass comprehensive_data as full_unfiltered_data so historical calculations are stable
    metrics = calculate_enhanced_metrics(final_filtered_data, unconstrained_data, max_constrained_carriers, carrier_facility_exclusions, comprehensive_data)
    
    if metrics is None:
        st.warning("⚠️ No data available after applying filters.")
        return
    
    # Display cost analysis dashboard - pass constraint data for proper cost calculation
    display_current_metrics(metrics, constrained_data, unconstrained_data)
    
    # Show detailed analysis table with constrained and unconstrained data
    # Pass carrier_facility_exclusions so scenarios respect facility-level exclusions
    # Pass comprehensive_data as full_unfiltered_data so historical calculations are stable
    show_detailed_analysis_table(final_filtered_data, unconstrained_data, constrained_data, metrics, max_constrained_carriers, carrier_facility_exclusions, comprehensive_data)
    
    # 🔬 DIAGNOSTIC TOOL - Enable to debug container count discrepancies

    # Advanced Analytics & Machine Learning and Interactive Visualizations are
    # hidden for now. Re-enable by uncommenting the two calls below.
    # show_advanced_analytics(final_filtered_data)
    # show_interactive_visualizations(final_filtered_data)

    # Show historic volume analysis at the bottom (uses filtered data to match current view)
    # Isolated: a failure in this panel must not take down the carrier flip report below.
    st.markdown("---")
    try:
        show_historic_volume_analysis(final_filtered_data, n_weeks=5)
    except Exception as e:
        logger.exception("Historic volume analysis failed")
        st.error(f"❌ Historic Volume Analysis could not be displayed: {e}")

    # Carrier Flip Analysis — reuses the loaded per-container GVT and Rate data.
    # The allocation it analyzes already reflects the active filters (it comes from the
    # Detailed Analysis Table, which runs on final_filtered_data). The GVT, however, is
    # the full per-container sheet, so filter it with the SAME active filters before
    # handing it over — otherwise the flip report's GVT rows, match counts, and table
    # would include containers outside the current view. GVT carries the exact columns
    # the filters key on (Discharged Port, Facility, Week Number, Dray SCAC(FL)), so we
    # reuse apply_filters_to_data to keep the filtering logic in one place.
    # Isolated for the same reason — render the flip report even if a sibling panel errors.
    st.markdown("---")
    try:
        filtered_gvt, _, _, _, _ = apply_filters_to_data(GVTdata)
        show_carrier_flip_report(in_app_gvt=filtered_gvt, in_app_rate=Ratedata)
    except Exception as e:
        logger.exception("Carrier flip report failed")
        st.error(f"❌ Carrier Flip Analysis could not be displayed: {e}")

    # JBH Allocation Model — independent of the filters/flow above; takes its own
    # per-container Inbound Container Milestone upload and a port selection.
    # TEMPORARILY HIDDEN — re-enable by uncommenting the two lines below (and the
    # import near the top of this file) when returning to the JBH work.
    # st.markdown("---")
    # show_jbh_allocation_report(in_app_gvt=GVTdata)

    # Footer
    show_footer()

if __name__ == "__main__":
    main()
