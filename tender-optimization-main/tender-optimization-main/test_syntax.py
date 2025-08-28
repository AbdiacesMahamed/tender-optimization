#!/usr/bin/env python3
"""
Simple syntax validation script for the optimization modules
"""

import ast
import sys
import os

def check_syntax(file_path):
    """Check if a Python file has valid syntax"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse the file to check syntax
        ast.parse(content, filename=file_path)
        return True, None
    except SyntaxError as e:
        return False, f"Syntax error: {e}"
    except Exception as e:
        return False, f"Error reading file: {e}"

def main():
    """Test the main optimization files"""
    files_to_check = [
        'components/optimization.py',
        'components/optimization_calculations.py', 
        'components/optimization_ui.py'
    ]
    
    print("🔍 Checking syntax of optimization modules...")
    all_good = True
    
    for file_path in files_to_check:
        if os.path.exists(file_path):
            is_valid, error = check_syntax(file_path)
            if is_valid:
                print(f"✅ {file_path}: Syntax OK")
            else:
                print(f"❌ {file_path}: {error}")
                all_good = False
        else:
            print(f"⚠️  {file_path}: File not found")
            all_good = False
    
    if all_good:
        print("\n🎉 All optimization modules have valid syntax!")
        print("📁 File structure:")
        print("   - optimization.py: Main orchestrator (imports from both modules)")
        print("   - optimization_calculations.py: PuLP linear programming logic")
        print("   - optimization_ui.py: Streamlit UI components")
        return 0
    else:
        print("\n❌ Some files have syntax errors")
        return 1

if __name__ == "__main__":
    sys.exit(main())
