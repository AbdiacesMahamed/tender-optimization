"""
Script to remove all debug statements from the codebase
"""
import re
from pathlib import Path

def remove_debug_blocks(content):
    """Remove debug blocks from file content"""
    lines = content.split('\n')
    cleaned_lines = []
    in_debug_block = False
    debug_indent = 0
    
    for i, line in enumerate(lines):
        # Check if this is a debug comment or statement
        if '🔍 DEBUG' in line or 'st.write("🔍' in line or "st.write('🔍" in line:
            in_debug_block = True
            debug_indent = len(line) - len(line.lstrip())
            continue
        
        # If in debug block, skip lines with same or greater indentation
        if in_debug_block:
            current_indent = len(line) - len(line.lstrip())
            if line.strip() == '' or current_indent > debug_indent:
                continue
            else:
                in_debug_block = False
        
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)

def clean_file(filepath):
    """Clean a single file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        cleaned = remove_debug_blocks(content)
        
        if cleaned != content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(cleaned)
            print(f"✅ Cleaned: {filepath}")
            return True
        else:
            print(f"ℹ️  No changes: {filepath}")
            return False
    except Exception as e:
        print(f"❌ Error cleaning {filepath}: {e}")
        return False

# Files to clean
files_to_clean = [
    Path('components/data_loader.py'),
    Path('components/data_processor.py'),
    Path('components/metrics.py'),
    Path('dashboard.py'),
]

print("=" * 80)
print("REMOVING DEBUG STATEMENTS")
print("=" * 80)

cleaned_count = 0
for filepath in files_to_clean:
    if filepath.exists():
        if clean_file(filepath):
            cleaned_count += 1
    else:
        print(f"⚠️  File not found: {filepath}")

print(f"\n✅ Cleaned {cleaned_count} files")
print("=" * 80)
