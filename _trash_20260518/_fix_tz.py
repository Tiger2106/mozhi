"""Fix: Add SHANGHAI_TZ to src/config.py and replace all timezone(timedelta(hours=8))"""
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

PROJECT = Path(r'C:\Users\17699\mozhi_platform')

# Step 1: Add SHANGHAI_TZ to config.py
config_path = PROJECT / 'src' / 'config.py'
config_text = config_path.read_text(encoding='utf-8')

if 'SHANGHAI_TZ' not in config_text:
    insert_marker = "from pathlib import Path\n"
    insert_pos = config_text.find(insert_marker)
    if insert_pos == -1:
        raise RuntimeError("Cannot find import block in config.py")
    insert_pos += len(insert_marker)
    
    INSERT_BLOCK = """
from datetime import timezone, timedelta

SHANGHAI_TZ = timezone(timedelta(hours=8))
"""
    config_text = config_text[:insert_pos] + INSERT_BLOCK + config_text[insert_pos:]
    config_path.write_text(config_text, encoding='utf-8')
    print(f"[OK] Added SHANGHAI_TZ to {config_path}")
else:
    print(f"[SKIP] SHANGHAI_TZ already exists in config.py")

# Step 2: Replace timezone(timedelta(hours=8)) in src/ and scripts/
files_to_search = sorted(PROJECT.glob('src/**/*.py')) + sorted(PROJECT.glob('scripts/**/*.py'))

TZ8_PATTERN = re.compile(r'timezone\s*\(\s*timedelta\s*\(\s*hours\s*=\s*8\s*\)\s*\)')
IMPORT_SRC_CONFIG = re.compile(r'from\s+src\.config\s+import\s+(.+)')

count = 0
for pyfile in files_to_search:
    original = pyfile.read_text(encoding='utf-8')
    text = original
    
    if not TZ8_PATTERN.search(text):
        continue
    
    # Replace timezone(timedelta(hours=8)) with SHANGHAI_TZ
    text = TZ8_PATTERN.sub('SHANGHAI_TZ', text)
    
    # Add import if not already there
    import_statement = 'from src.config import SHANGHAI_TZ'
    if import_statement not in text:
        m = IMPORT_SRC_CONFIG.search(text)
        if m:
            existing = m.group(1)
            old_import_line = m.group(0)
            if 'SHANGHAI_TZ' not in existing:
                new_import_line = 'from src.config import ' + existing.strip() + ', SHANGHAI_TZ'
                text = text.replace(old_import_line, new_import_line)
        else:
            lines = text.split('\n')
            last_import_idx = -1
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith('import ') or stripped.startswith('from '):
                    last_import_idx = i
            
            if last_import_idx >= 0:
                indent = ' ' * (len(lines[last_import_idx]) - len(lines[last_import_idx].lstrip()))
                lines.insert(last_import_idx + 1, indent + import_statement)
                text = '\n'.join(lines)
    
    pyfile.write_text(text, encoding='utf-8')
    count += 1
    relative = pyfile.relative_to(PROJECT)
    print(f"  [FIX] {relative}")

print(f"\n[DONE] Updated {count} files total")
