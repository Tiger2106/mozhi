"""Debug: check report_enricher.py specifically"""
import re
from pathlib import Path

PROJECT = Path(r'C:\Users\17699\mozhi_platform')
pyfile = PROJECT / 'src/morning_pipeline/report_enricher.py'
original = pyfile.read_text(encoding='utf-8')

IMPORT_STMT = 'from src.config import SHANGHAI_TZ'
IMPORT_RE = re.compile(r'^\s*from src\.config import SHANGHAI_TZ\s*$', re.MULTILINE)

matches = list(IMPORT_RE.finditer(original))
print(f"File: {pyfile.relative_to(PROJECT)}")
print(f"Total matches: {len(matches)}")

indented = [m for m in matches if not m.group(0).startswith('from')]
top_level = [m for m in matches if m.group(0).startswith('from')]
print(f"Indented: {len(indented)}")
print(f"Top-level: {len(top_level)}")

lines = original.split('\n')
first_use = None
for i, line in enumerate(lines):
    stripped = line.strip()
    if 'SHANGHAI_TZ' in line and not IMPORT_RE.match(stripped):
        first_use = i
        print(f"First non-import SHANGHAI_TZ use at line {i+1}: {stripped[:60]}")
        break

# Check if first_use was never found
if first_use is None:
    print("No non-import SHANGHAI_TZ usage found in file!")
    # Check all SHANGHAI_TZ occurrences
    for i, line in enumerate(lines):
        if 'SHANGHAI_TZ' in line:
            print(f"  Line {i+1}: {line.strip()[:80]}")
