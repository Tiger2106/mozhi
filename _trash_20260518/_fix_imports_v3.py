"""Repair v3: handle `from __future__` and edge cases properly"""
import re
from pathlib import Path

PROJECT = Path(r'C:\Users\17699\mozhi_platform')

IMPORT_STMT = 'from src.config import SHANGHAI_TZ'
IMPORT_RE = re.compile(r'^\s*from src\.config import SHANGHAI_TZ\s*$', re.MULTILINE)

count = 0
errors = []
for pyfile in sorted(PROJECT.glob('src/**/*.py')) + sorted(PROJECT.glob('scripts/**/*.py')):
    original = pyfile.read_text(encoding='utf-8')
    
    matches = list(IMPORT_RE.finditer(original))
    if not matches:
        continue
    
    rel = pyfile.relative_to(PROJECT).as_posix()
    
    # Check if any import is indented
    indented = [m for m in matches if m.group(0).startswith(' ')]
    
    # Check ordering
    lines = original.split('\n')
    first_use_line = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if 'SHANGHAI_TZ' in s and not IMPORT_RE.match(line if line.endswith('\n') else line + '\n'):
            first_use_line = i
            break
    
    needs_fix = bool(indented)
    
    if not indented and first_use_line >= 0:
        for m in matches:
            line_idx = None
            for i, line in enumerate(lines):
                if line == m.group(0).rstrip('\n'):
                    line_idx = i
                    break
            if line_idx is not None and first_use_line < line_idx:
                needs_fix = True
                break
    
    if not needs_fix:
        continue
    
    print(f"[FIX] {rel}")
    
    # Remove ALL matches
    cleaned = original
    for m in reversed(matches):
        cleaned = cleaned[:m.start()] + cleaned[m.end():]
    while '\n\n\n' in cleaned:
        cleaned = cleaned.replace('\n\n\n', '\n\n')
    
    code_lines = cleaned.split('\n')
    
    # Walk preamble to find insertion point
    # Skip: shebang, encoding, docstrings, blank lines, comments, imports
    # The correct insertion point is AFTER from __future__ but BEFORE all other imports
    # OR after the last import before any code
    
    i = 0
    last_import_idx = -1
    future_import_idx = -1
    
    while i < len(code_lines):
        stripped = code_lines[i].strip()
        
        # Skip shebang
        if i == 0 and stripped.startswith('#!'):
            i += 1
            continue
        # Skip encoding
        if i <= 2 and stripped in ('# -*- coding: utf-8 -*-', '# coding: utf-8'):
            i += 1
            continue
        # Skip docstring start
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if stripped[3:] and ('"""' in stripped[3:] or "'''" in stripped[3:]):
                i += 1  # single-line docstring
                continue
            # Multi-line: skip until closing
            i += 1
            while i < len(code_lines):
                if '"""' in code_lines[i] or "'''" in code_lines[i]:
                    i += 1
                    break
                i += 1
            continue
        # Skip blank
        if not stripped:
            i += 1
            continue
        # Skip comments
        if stripped.startswith('#'):
            i += 1
            continue
        # Handle imports
        if stripped.startswith('from ') or stripped.startswith('import '):
            if stripped.startswith('from __future__') or stripped.startswith('import __future__'):
                future_import_idx = i
            last_import_idx = i
            i += 1
            continue
        # Found code
        break
    
    # Determine insertion point
    if future_import_idx >= 0:
        # Insert after the last __future__ import
        insert_line = future_import_idx + 1
        # But before other imports... actually which other imports?
        # Let me redo - we want to insert after the last standard import
        # If future_import was found, the rest of the loop continued to find more imports
        # The last_import_idx is already capturing the last import
        pass
    
    insert_line = last_import_idx + 1
    
    indent = '  '  # default
    if last_import_idx >= 0:
        indent = ' ' * (len(code_lines[last_import_idx]) - len(code_lines[last_import_idx].lstrip()))
    else:
        # Find the first code line for indentation
        for j in range(i, len(code_lines)):
            if code_lines[j].strip():
                indent = ' ' * (len(code_lines[j]) - len(code_lines[j].lstrip()))
                break
    
    # Check if we'd insert before from __future__
    # If there are imports after __future__, our insert_line should be after __future__
    # Actually last_import_idx already handles this because it tracks ALL imports
    
    code_lines.insert(insert_line, indent + IMPORT_STMT)
    cleaned = '\n'.join(code_lines)
    
    # Verify: try to compile
    try:
        compile(cleaned, str(pyfile), 'exec')
    except SyntaxError as e:
        errors.append((rel, str(e)))
    
    pyfile.write_text(cleaned, encoding='utf-8')
    count += 1

if errors:
    print(f"\n⚠️  {len(errors)} syntax errors to fix:")
    for rel, err in errors:
        print(f"  {rel}: {err}")
else:
    print(f"\n[DONE] Fixed {count} files — all syntax OK")
