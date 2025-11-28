"""
Test script to verify all imports work correctly
"""
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

print("Testing imports...")

try:
    print("\n1. Testing config_styling import...")
    from components.config_styling import section_header
    print("   ✓ config_styling OK")
except Exception as e:
    print(f"   ✗ config_styling FAILED: {e}")

try:
    print("\n2. Testing data_loader import...")
    from components.data_loader import show_file_upload_section
    print("   ✓ data_loader OK")
except Exception as e:
    print(f"   ✗ data_loader FAILED: {e}")

try:
    print("\n3. Testing optimization.performance_logic import...")
    from optimization.performance_logic import allocate_to_highest_performance
    print("   ✓ optimization.performance_logic OK")
except Exception as e:
    print(f"   ✗ optimization.performance_logic FAILED: {e}")

try:
    print("\n4. Testing utils import...")
    from components.utils import get_rate_columns, count_containers, parse_container_ids
    print("   ✓ utils OK")
except Exception as e:
    print(f"   ✗ utils FAILED: {e}")

try:
    print("\n5. Testing constraints_processor import DIRECTLY...")
    from components.constraints_processor import process_constraints_file, apply_constraints_to_data, show_constraints_summary
    print("   ✓ constraints_processor OK")
    print(f"   Functions found: {[process_constraints_file.__name__, apply_constraints_to_data.__name__, show_constraints_summary.__name__]}")
except Exception as e:
    print(f"   ✗ constraints_processor FAILED: {e}")
    import traceback
    traceback.print_exc()

try:
    print("\n6. Testing full components import...")
    from components import process_constraints_file, apply_constraints_to_data, show_constraints_summary
    print("   ✓ Full components import OK")
    print(f"   Functions accessible: {[process_constraints_file.__name__, apply_constraints_to_data.__name__, show_constraints_summary.__name__]}")
except Exception as e:
    print(f"   ✗ Full components import FAILED: {e}")
    import traceback
    traceback.print_exc()

print("\n✅ All tests completed!")
