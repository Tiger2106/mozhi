"""Repair: move indented from src.config import SHANGHAI_TZ to module top-level"""
import re
from pathlib import Path

PROJECT = Path(r'C:\Users\17699\mozhi_platform')

IMPORT_STMT = 'from src.config import SHANGHAI_TZ'
IMPORT_RE = re.compile(r'^\s*from src\.config import SHANGHAI_TZ\s*$')

count = 0
for pyfile in sorted(PROJECT.glob('src/**/*.py')) + sorted(PROJECT.glob('scripts/**/*.py')):
    original = pyfile.read_text(encoding='utf-8')
    
    # Find all occurrences
    matches = list(IMPORT_RE.finditer(original, re.MULTILINE))
    if not matches:
        continue
    
    # Determine if any import is indented (not at start of line col 0)
    indented = [m for m in matches if not m.group(0).startswith('from')]
    top_level = [m for m in matches if m.group(0).startswith('from')]
    
    # Check ordering even for top-level imports
    lines = original.split('\n')
    first_use = None
    for i, line in enumerate(lines):
        if 'SHANGHAI_TZ' in line and not IMPORT_RE.match(line):
            first_use = i
            break
    
    needs_fix = bool(indented)
    
    if top_level and first_use is not None:
        # Find the line number of the last top-level import
        last_top_import = max(m.group(0) for m in top_level)
        last_top_line = None
        for i, line in enumerate(lines):
            if line == last_top_import:
                last_top_line = i
                break
        if last_top_line is not None and first_use < last_top_line:
            # Import is top-level but after usage — still broken
            needs_fix = True
    
    if not needs_fix:
        continue
    
    # Remove ALL SHANGHAI_TZ imports from the file
    cleaned = original
    for m in reversed(matches):
        cleaned = cleaned[:m.start()] + cleaned[m.end():]
    
    # Clean up blank lines
    cleaned = re.sub(r'\n\n\n+', '\n\n', cleaned)
    
    # Find where to insert the import in the preamble
    # Walk from top, track last module-level import line
    code_lines = cleaned.split('\n')
    preamble_end = 0  # line index where code starts (after preamble)
    last_import_idx = -1
    
    for i, line in enumerate(code_lines):
        stripped = line.strip()
        # Skip shebang, encoding, docstring, blank lines, comments
        if i == 0 and stripped.startswith('#!'):
            preamble_end = i + 1
            continue
        if i <= 2 and stripped in ('# -*- coding: utf-8 -*-', '# coding: utf-8'):
            preamble_end = i + 1
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # Find the end of the docstring
            # Simple case: single-line docstring
            if stripped[3:] and ('"""' in stripped[3:] or "'''" in stripped[3:]):
                preamble_end = i + 1
                continue
            # Multi-line docstring
            end_found = False
            for j in range(i + 1, min(i + 50, len(code_lines))):
                if '"""' in code_lines[j] or "'''" in code_lines[j]:
                    preamble_end = j + 1
                    end_found = True
                    break
            if end_found:
                continue
            break
        if not stripped:
            preamble_end = i + 1
            continue
        if stripped.startswith('#'):
            preamble_end = i + 1
            continue
        if stripped.startswith('from ') or stripped.startswith('import '):
            preamble_end = i + 1
            last_import_idx = i
            continue
        # Found actual code
        break
    
    # Insert import after the last import line, or at preamble_end
    insert_line = last_import_idx + 1 if last_import_idx >= 0 else preamble_end
    indent = ''
    if last_import_idx >= 0:
        indent = ' ' * (len(code_lines[last_import_idx]) - len(code_lines[last_import_idx].lstrip()))
    
    code_lines.insert(insert_line, indent + IMPORT_STMT)
    cleaned = '\n'.join(code_lines)
    
    pyfile.write_text(cleaned, encoding='utf-8')
    count += 1
    print(f"[FIX] {pyfile.relative_to(PROJECT).as_posix()}")

print(f"\n[DONE] Fixed {count} files")
