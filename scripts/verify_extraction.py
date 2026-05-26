#!/usr/bin/env python3
"""Verify PDF text extraction is correct by writing to a file."""
from pdfminer.high_level import extract_text

path = r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf'
text = extract_text(path, maxpages=5)

# Write extracted text to file for inspection
out_path = r'C:\Users\17699\mozhi_platform\reports\pdf\_extracted_text.txt'
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(text)

# Count CJK characters
cn = sum(1 for c in text if ord(c) > 0x4E00 and ord(c) < 0x9FFF)
print(f'Total chars: {len(text)}')
print(f'CJK chars (first 5 pages): {cn}')

# Check for expected content
checks = [
    '601857', '18.16%', '2.75%', 'Sharpe', 'DISTRIB', 'EXHAUST',
    'Layer 1', 'Layer 2', '假突破', '生命周期', '置信度',
    '回撤', '收益', '信号', 'Calmar', 'MEDIUM',
    'PRE_INIT', 'MA_UP', 'MA_DOWN', 'BOLL_UP',
    '中国石油', '总收益率', '年化', '夏普',
]
for c in checks:
    if c in text:
        print(f'  [OK] Found: {c}')
    else:
        print(f'  [WARN] NOT found: {c}')

# Check the beginning of text to verify content
print(f'\n--- First 200 chars ---')
print(text[:200])

# Check a section with Chinese
idx = text.find('Layer 2')
if idx >= 0:
    print(f'\n--- Around Layer 2 ---')
    print(text[idx:idx+300])
    
print(f'\nExtracted text saved to: {out_path}')
