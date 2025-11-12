import re
from pathlib import Path

def remove_debug_blocks(filepath):
    """Remove debug blocks more aggressively"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    cleaned = []
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check if this line contains a debug marker
        if ('DEBUG' in line and ('st.write' in line or '#' in line)) or '🔍' in line:
            # Get the indentation level
            base_indent = len(line) - len(line.lstrip())
            
            # Skip this line
            i += 1
            
            # Skip all following lines that are more indented or empty
            while i < len(lines):
                next_line = lines[i]
                next_indent = len(next_line) - len(next_line.lstrip())
                
                # Stop if we hit a line with same or less indentation (unless it's empty)
                if next_line.strip() and next_indent <= base_indent:
                    break
                    
                i += 1
            continue
        
        cleaned.append(line)
        i += 1
    
    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(cleaned)
    
    print(f'✅ Cleaned: {filepath}')

# Clean files
files = [
    'components/data_loader.py',
    'components/metrics.py',
    'dashboard.py'
]

for f in files:
    filepath = Path(f)
    if filepath.exists():
        remove_debug_blocks(filepath)
        
print('\n✅ All debug statements removed!')
