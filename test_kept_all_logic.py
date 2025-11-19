"""
Test to verify "kept all" vs "Lost X" logic is working correctly.

This tests the specific bug where carriers showed "(kept all)" 
even when they had lost containers.
"""

import sys
import pandas as pd

# Import directly from the module file to avoid streamlit dependency
sys.path.insert(0, 'components')
import container_tracer
from container_tracer import (
    build_container_origin_map,
    trace_container_movements,
    format_flip_details
)

print("=" * 60)
print("TESTING 'KEPT ALL' vs 'LOST' LOGIC")
print("=" * 60)

# Scenario 1: FRQT had 23 originally, now has 14 (lost 9)
# This should show "Lost 9", NOT "(kept all)"
original_data_1 = pd.DataFrame([{
    'Dray SCAC(FL)': 'FRQT',
    'Container Numbers': 'C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, C14, C15, C16, C17, C18, C19, C20, C21, C22, C23',
    'Discharged Port': 'USBAL',
    'Lane': 'HGRG-S',
    'Facility': 'HIA1',
    'Terminal': 'TRM-SEAGIRT',
    'Category': 'Retail CD',
    'Week Number': 46
}])

current_data_1 = pd.DataFrame([{
    'Dray SCAC(FL)': 'FRQT',
    'Container Numbers': 'C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, C14',  # Only 14 of the original 23
    'Discharged Port': 'USBAL',
    'Lane': 'HGRG-S',
    'Facility': 'HIA1',
    'Terminal': 'TRM-SEAGIRT',
    'Category': 'Retail CD',
    'Week Number': 46
}])

# Scenario 2: RKNE had 20 originally, now has 8 (lost 12)
# This should show "Lost 12", NOT "(kept all)"
original_data_2 = pd.DataFrame([{
    'Dray SCAC(FL)': 'RKNE',
    'Container Numbers': 'R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14, R15, R16, R17, R18, R19, R20',
    'Discharged Port': 'USBAL',
    'Lane': 'HGRG-S',
    'Facility': 'HIA1',
    'Terminal': 'TRM-SEAGIRT',
    'Category': 'Retail CD',
    'Week Number': 42
}])

current_data_2 = pd.DataFrame([{
    'Dray SCAC(FL)': 'RKNE',
    'Container Numbers': 'R1, R2, R3, R4, R5, R6, R7, R8',  # Only 8 of the original 20
    'Discharged Port': 'USBAL',
    'Lane': 'HGRG-S',
    'Facility': 'HIA1',
    'Terminal': 'TRM-SEAGIRT',
    'Category': 'Retail CD',
    'Week Number': 42
}])

# Scenario 3: Carrier truly kept all containers (no change)
# This SHOULD show "(kept all)"
original_data_3 = pd.DataFrame([{
    'Dray SCAC(FL)': 'ATMI',
    'Container Numbers': 'A1, A2, A3, A4, A5',
    'Discharged Port': 'USBAL',
    'Lane': 'HGRG-S',
    'Facility': 'HIA1',
    'Terminal': 'TRM-SEAGIRT',
    'Category': 'Retail CD',
    'Week Number': 50
}])

current_data_3 = pd.DataFrame([{
    'Dray SCAC(FL)': 'ATMI',
    'Container Numbers': 'A1, A2, A3, A4, A5',  # All 5 original containers
    'Discharged Port': 'USBAL',
    'Lane': 'HGRG-S',
    'Facility': 'HIA1',
    'Terminal': 'TRM-SEAGIRT',
    'Category': 'Retail CD',
    'Week Number': 50
}])

# Test each scenario
print("\nTest 1: FRQT had 23, now has 14")
print("-" * 60)
origin_map_1 = build_container_origin_map(original_data_1)
trace_1 = trace_container_movements(current_data_1, origin_map_1)
result_1 = format_flip_details(trace_1[0], show_container_ids=False)
print(f"Result: {result_1}")
print(f"Original count: {trace_1[0]['original_count']}")
print(f"Current count: {trace_1[0]['current_count']}")
print(f"Kept: {trace_1[0]['total_kept']}")

if "Lost 9" in result_1:
    print("✅ PASS: Shows 'Lost 9' correctly")
elif "(kept all)" in result_1:
    print("❌ FAIL: Still showing '(kept all)' incorrectly")
else:
    print("⚠️ UNEXPECTED: Neither 'Lost 9' nor '(kept all)' found")

print("\nTest 2: RKNE had 20, now has 8")
print("-" * 60)
origin_map_2 = build_container_origin_map(original_data_2)
trace_2 = trace_container_movements(current_data_2, origin_map_2)
result_2 = format_flip_details(trace_2[0], show_container_ids=False)
print(f"Result: {result_2}")
print(f"Original count: {trace_2[0]['original_count']}")
print(f"Current count: {trace_2[0]['current_count']}")
print(f"Kept: {trace_2[0]['total_kept']}")

if "Lost 12" in result_2:
    print("✅ PASS: Shows 'Lost 12' correctly")
elif "(kept all)" in result_2:
    print("❌ FAIL: Still showing '(kept all)' incorrectly")
else:
    print("⚠️ UNEXPECTED: Neither 'Lost 12' nor '(kept all)' found")

print("\nTest 3: ATMI had 5, still has 5 (kept all)")
print("-" * 60)
origin_map_3 = build_container_origin_map(original_data_3)
trace_3 = trace_container_movements(current_data_3, origin_map_3)
result_3 = format_flip_details(trace_3[0], show_container_ids=False)
print(f"Result: {result_3}")
print(f"Original count: {trace_3[0]['original_count']}")
print(f"Current count: {trace_3[0]['current_count']}")
print(f"Kept: {trace_3[0]['total_kept']}")

if "(kept all)" in result_3:
    print("✅ PASS: Shows '(kept all)' correctly")
else:
    print("❌ FAIL: Should show '(kept all)' but doesn't")

print("\n" + "=" * 60)
print("LOGIC CHECK COMPLETE")
print("=" * 60)
