"""Repair: move indented from src.config import SHANGHAI_TZ to module top-level - v2"""
import re
from pathlib import Path

PROJECT = Path(r'C:\Users\17699\mozhi_platform')

IMPORT_STMT = 'from src.config import SHANGHAI_TZ'
IMPORT_RE = re.compile(r'^\s*from src\.config import SHANGHAI_TZ\s*$', re.MULTILINE)

count = 0
for pyfile in sorted(PROJECT.glob('src/**/*.py')) + sorted(PROJECT.glob('scripts/**/*.py')):
    original = pyfile.read_text(encoding='utf-8')
    
    matches = list(IMPORT_RE.finditer(original))
    if not matches:
        continue
    
    rel = pyfile.relative_to(PROJECT).as_posix()
    
    # Classify matches: indented vs top-level
    indented = [m for m in matches if m.group(0).startswith(' ')]
    top_level = [m for m in matches if m.group(0).startswith('from')]
    
    # Check ordering for top-level imports
    lines = original.split('\n')
    first_use = None
    first_use_line = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if 'SHANGHAI_TZ' in s and not IMPORT_RE.match(s + '\n'):
            first_use = s
            first_use_line = i
            break
    
    needs_fix = bool(indented)
    
    if top_level and first_use_line >= 0:
        # Find the LAST top-level import line
        last_top_idx = -1
        for i, line in enumerate(lines):
            if IMPORT_RE.match(line):
                last_top_idx = i
        if first_use_line < last_top_idx:
            needs_fix = True
    
    if not needs_fix:
        print(f"[OK ] {rel}")
        continue
    
    print(f"[FIX] {rel}: {'indented' if indented else 'ordering'} ({len(matches)} match(es))")
    
    # Remove all SHANGHAI_TZ imports
    cleaned = original
    for m in reversed(matches):
        cleaned = cleaned[:m.start()] + cleaned[m.end():]
    # Clean blank lines
    while '\n\n\n' in cleaned:
        cleaned = cleaned.replace('\n\n\n', '\n\n')
    
    code_lines = cleaned.split('\n')
    last_import_idx = -1
    
    for i, line in enumerate(code_lines):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            last_import_idx = i
            continue
        if stripped.startswith('from ') or stripped.startswith('import '):
            last_import_idx = i
            continue
        # Found actual code or docstring
        break
    
    insert_line = last_import_idx + 1
    indent = ''
    if last_import_idx >= 0:
        indent = ' ' * (len(code_lines[last_import_idx]) - len(code_lines[last_import_idx].lstrip()))
    
    code_lines.insert(insert_line, indent + IMPORT_STMT)
    cleaned = '\n'.join(code_lines)
    
    pyfile.write_text(cleaned, encoding='utf-8')
    count += 1

print(f"\n[DONE] Fixed {count} files")
