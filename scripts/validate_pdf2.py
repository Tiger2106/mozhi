#!/usr/bin/env python3
"""Validate generated PDF for CJK content - using pdfminer."""
import os
path = r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf'

size = os.path.getsize(path)
print(f"Size: {size:,} bytes")

from pdfminer.high_level import extract_text
text = extract_text(path, maxpages=3)
cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
total = len(text)
print(f"Total chars extracted: {total}")
print(f"Chinese chars (page 1-3): {cn}")
print(f"Sample (first 500 chars):\n{text[:500]}")
print(f"\nCheck for English keywords:")
for kw in ['601857', '18.16%', 'Layer', 'DISTRIB', 'EXHAUST', 'Sharpe', 'SimSun']:
    if kw.lower() in text.lower():
        print(f"  [OK] Found: {kw}")
    else:
        print(f"  [WARN] NOT found: {kw}")
print("\n[OK] Validation complete")
