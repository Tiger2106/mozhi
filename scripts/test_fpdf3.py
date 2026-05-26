#!/usr/bin/env python3
"""Test fpdf2 with SimHei TTF (single font, not TTC collection)."""
import os, re
from fpdf import FPDF
from pdfminer.high_level import extract_text

pdf = FPDF()
pdf.add_page()

# Use SimHei.ttf (single TTF, not TTC collection)
font_path = r'C:\Windows\Fonts\simhei.ttf'
pdf.add_font('SimHei', '', font_path)
pdf.set_font('SimHei', '', 12)

lines = [
    '中文测试：收益率18.16%，年化2.75%，夏普0.76',
    'English: Sharpe=0.76, Layer 1, DISTRIB 81.62%',
    '收益矩阵：MEDIUM×TREND_UP最佳，Sharpe 0.62',
    '资本效率：利用率27.9%，闲置72.1%',
    '假突破分析：突破909次，假突破119次（13.09%）',
    '生命周期：DISTRIB 81.6%，PRE_INIT 16.3%',
    '最大回撤 2.38%，Calmar比率 1.15',
]
for text in lines:
    pdf.multi_cell(0, 8, text)

# Save
test_path = r'C:\Users\17699\mozhi_platform\reports\pdf\_fpdf_test3.pdf'
pdf.output(test_path)
print(f'[OK] Generated: {test_path}')
print(f'Size: {os.path.getsize(test_path):,} bytes')

# Check raw PDF
with open(test_path, 'rb') as f:
    raw = f.read()

for m in re.finditer(rb'/BaseFont\s+/\S+', raw):
    print(f'  BaseFont: {m.group().decode("latin-1")}')
    
ff2 = raw.count(b'/FontFile2')
print(f'  FontFile2 streams: {ff2}')
has_ttf = raw.count(b'\x00\x01\x00\x00\x00')
print(f'  TTF magic headers: {has_ttf}')

# pdfminer extraction
text = extract_text(test_path)
cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
print(f'\npdfminer: CJK chars={cn}')
print(f'  Sample: {repr(text[:300])}')

expected = '中文测试'
print(f'  Expected "{expected}" found: {"中文测试" in text}')
print(f'  Expected "收益率" found: {"收益率" in text}')
print(f'  Expected "Sharp" found: {"Sharpe" in text}')
