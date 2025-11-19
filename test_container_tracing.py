"""
Test script for container-level tracing functionality

This script validates that the container tracing system correctly:
1. Builds origin maps from baseline data
2. Traces container movements between carriers
3. Formats flip details accurately
4. Calculates movement summaries
"""
import pandas as pd
import sys
from pathlib import Path

# Add components to path
sys.path.insert(0, str(Path(__file__).parent))

from components.container_tracer import (
    parse_container_ids,
    build_container_origin_map,
    trace_container_movements,
    format_flip_details,
    add_detailed_carrier_flips_column,
    get_container_movement_summary
)

def test_parse_container_ids():
    """Test container ID parsing"""
    print("\n" + "="*60)
    print("TEST 1: Parse Container IDs")
    print("="*60)
    
    tests = [
        ("MSDU123, TCKU456, MSNU789", 3),
        ("MSDU123,TCKU456", 2),
        ("MSDU123", 1),
        ("", 0),
        (None, 0),
    ]
    
    for container_str, expected_count in tests:
        result = parse_container_ids(container_str)
        status = "✓" if len(result) == expected_count else "✗"
        print(f"{status} Input: {repr(container_str)}")
        print(f"   Expected: {expected_count} IDs, Got: {len(result)} IDs")
        if result:
            print(f"   IDs: {result}")
    
    print("\n✅ Container ID parsing test complete")


def test_origin_mapping():
    """Test building origin map from baseline data"""
    print("\n" + "="*60)
    print("TEST 2: Build Origin Map")
    print("="*60)
    
    # Create sample baseline data
    baseline_data = pd.DataFrame({
        'Dray SCAC(FL)': ['ATMI', 'RKNE', 'XPDR'],
        'Week Number': [46, 46, 46],
        'Discharged Port': ['BAL', 'BAL', 'BAL'],
        'Lane': ['USBALHIA1', 'USBALHIA1', 'USBALHIA1'],
        'Facility': ['HIA1', 'HIA1', 'HIA1'],
        'Terminal': ['TRM-SEAGIRT', 'TRM-SEAGIRT', 'TRM-SEAGIRT'],
        'Category': ['Retail CD', 'Retail CD', 'Retail CD'],
        'Container Numbers': [
            'MSDU123, MSDU234, MSDU345, MSDU456',
            'TCKU111, TCKU222, TCKU333',
            'XPDR001, XPDR002'
        ]
    })
    
    origin_map = build_container_origin_map(baseline_data)
    
    print(f"✓ Created origin map with {len(origin_map)} containers")
    print(f"\nSample mappings:")
    for container_id, info in list(origin_map.items())[:3]:
        print(f"  {container_id}: Carrier={info['original_carrier']}, Week={info['week']}")
    
    # Verify specific containers
    assert origin_map['MSDU123']['original_carrier'] == 'ATMI', "MSDU123 should map to ATMI"
    assert origin_map['TCKU111']['original_carrier'] == 'RKNE', "TCKU111 should map to RKNE"
    assert origin_map['XPDR001']['original_carrier'] == 'XPDR', "XPDR001 should map to XPDR"
    
    print("\n✅ Origin mapping test complete")
    return baseline_data, origin_map


def test_movement_tracing(baseline_data, origin_map):
    """Test tracing container movements"""
    print("\n" + "="*60)
    print("TEST 3: Trace Container Movements")
    print("="*60)
    
    # Create current data with some containers moved
    current_data = pd.DataFrame({
        'Dray SCAC(FL)': ['ATMI', 'RKNE', 'FROT'],
        'Container Numbers': [
            'MSDU123, MSDU234, TCKU111, TCKU222',  # ATMI kept 2, got 2 from RKNE
            'TCKU333, XPDR001',  # RKNE lost 2 to ATMI, got 1 from XPDR
            'MSDU345, MSDU456, XPDR002'  # FROT (new) got 2 from ATMI, 1 from XPDR
        ]
    })
    
    trace_results = trace_container_movements(current_data, origin_map)
    
    print("\nRow 0 (ATMI):")
    result = trace_results[0]
    print(f"  Kept: {result['total_kept']} containers")
    print(f"  Flipped: {result['total_flipped']} containers")
    print(f"  Flip summary: {result['flip_summary']}")
    
    print("\nRow 1 (RKNE):")
    result = trace_results[1]
    print(f"  Kept: {result['total_kept']} containers")
    print(f"  Flipped: {result['total_flipped']} containers")
    print(f"  Flip summary: {result['flip_summary']}")
    
    print("\nRow 2 (FROT):")
    result = trace_results[2]
    print(f"  Kept: {result['total_kept']} containers")
    print(f"  Flipped: {result['total_flipped']} containers")
    print(f"  Flip summary: {result['flip_summary']}")
    
    # Verify expectations
    assert trace_results[0]['total_kept'] == 2, "ATMI should have kept 2"
    assert trace_results[0]['flip_summary'].get('RKNE', 0) == 2, "ATMI should have gained 2 from RKNE"
    assert trace_results[2]['total_kept'] == 0, "FROT should have kept 0 (new carrier)"
    assert trace_results[2]['total_flipped'] == 3, "FROT should have gained 3 total"
    
    print("\n✅ Movement tracing test complete")
    return current_data, trace_results


def test_display_formatting(trace_results):
    """Test formatting of trace results into display strings"""
    print("\n" + "="*60)
    print("TEST 4: Format Display Strings")
    print("="*60)
    
    for idx, result in enumerate(trace_results):
        formatted = format_flip_details(result, show_container_ids=False)
        print(f"\nRow {idx}: {formatted}")
    
    # Test with container IDs shown
    print("\n--- With Container IDs ---")
    for idx, result in enumerate(trace_results):
        formatted = format_flip_details(result, show_container_ids=True)
        print(f"\nRow {idx}:\n{formatted}")
    
    print("\n✅ Display formatting test complete")


def test_detailed_column(current_data, baseline_data):
    """Test adding detailed carrier flips column"""
    print("\n" + "="*60)
    print("TEST 5: Add Detailed Carrier Flips Column")
    print("="*60)
    
    result_data = add_detailed_carrier_flips_column(
        current_data.copy(), 
        baseline_data
    )
    
    print("\nResulting DataFrame:")
    print(result_data[['Dray SCAC(FL)', 'Container Numbers', 'Carrier Flips (Detailed)']])
    
    assert 'Carrier Flips (Detailed)' in result_data.columns, "Column should be added"
    
    print("\n✅ Detailed column test complete")


def test_movement_summary(current_data, baseline_data):
    """Test movement summary statistics"""
    print("\n" + "="*60)
    print("TEST 6: Movement Summary Statistics")
    print("="*60)
    
    summary = get_container_movement_summary(current_data, baseline_data)
    
    print(f"\nTotal Containers: {summary['total_containers']}")
    print(f"Total Kept: {summary['total_kept']} ({summary['kept_percentage']:.1f}%)")
    print(f"Total Flipped: {summary['total_flipped']} ({summary['flipped_percentage']:.1f}%)")
    print(f"Total Unknown: {summary['total_unknown']}")
    
    print(f"\nTop Flows:")
    for from_carrier, to_carrier, count in summary['top_flows']:
        print(f"  {from_carrier} → {to_carrier}: {count} containers")
    
    # Verify math
    total = summary['total_kept'] + summary['total_flipped'] + summary['total_unknown']
    assert total == summary['total_containers'], "Totals should add up"
    
    print("\n✅ Movement summary test complete")


def run_all_tests():
    """Run all tests"""
    print("\n" + "="*60)
    print("CONTAINER TRACING TEST SUITE")
    print("="*60)
    
    try:
        # Test 1: Parse container IDs
        test_parse_container_ids()
        
        # Test 2: Build origin map
        baseline_data, origin_map = test_origin_mapping()
        
        # Test 3: Trace movements
        current_data, trace_results = test_movement_tracing(baseline_data, origin_map)
        
        # Test 4: Format display
        test_display_formatting(trace_results)
        
        # Test 5: Add detailed column
        test_detailed_column(current_data, baseline_data)
        
        # Test 6: Movement summary
        test_movement_summary(current_data, baseline_data)
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        
    except Exception as e:
        print("\n" + "="*60)
        print("❌ TEST FAILED!")
        print("="*60)
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
