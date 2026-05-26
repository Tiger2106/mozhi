#!/usr/bin/env python3
"""fpdf2 CJK test with cell() instead of multi_cell."""
import os
from fpdf import FPDF

pdf = FPDF('P', 'mm', 'A4')
pdf.add_page()

# Use SimHei.ttf
font_path = r'C:\Windows\Fonts\simhei.ttf'
pdf.add_font('CJK', '', font_path)
pdf.set_font('CJK', '', 12)

pdf.cell(0, 10, '中文测试：收益率18.16%，年化2.75%，夏普0.76', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 10, 'English: Sharpe=0.76, Layer 1, DISTRIB 81.62%', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 10, '收益矩阵：MEDIUM×TREND_UP最佳，Sharpe 0.62', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 10, '资本效率：利用率27.9%，闲置72.1%', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 10, '假突破分析：突破909次，假突破119次（13.09%）', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 10, '生命周期：DISTRIB 81.6%，PRE_INIT 16.3%', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 10, '最大回撤 2.38%，Calmar比率 1.15', new_x="LMARGIN", new_y="NEXT")

test_path = r'C:\Users\17699\mozhi_platform\reports\pdf\_fpdf_test4.pdf'
pdf.output(test_path)
print(f'[OK] Size: {os.path.getsize(test_path):,} bytes')

# Check fonts
import re
with open(test_path, 'rb') as f:
    raw = f.read()
    
for m in re.finditer(rb'/BaseFont\s+/\S+', raw):
    print(f'  BaseFont: {m.group().decode("latin-1")}')
ff2 = raw.count(b'/FontFile2')
print(f'  FontFile2: {ff2}')
ttf = raw.count(b'\x00\x01\x00\x00\x00')
print(f'  TTF magic: {ttf}')

# Verify text extraction
from pdfminer.high_level import extract_text
try:
    text = extract_text(test_path)
    print(f'\n--- pdfminer extraction ---')
    print(text[:300])
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    print(f'CJK chars: {cn}')
    print(f'Contains "中文测试": {"中文测试" in text}')
    print(f'Contains "收益率": {"收益率" in text}')
except Exception as e:
    print(f'pdfminer error: {e}')
