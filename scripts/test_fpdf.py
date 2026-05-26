#!/usr/bin/env python3
"""Test fpdf2 with CJK fonts."""
import os
from fpdf import FPDF

class CJKPDF(FPDF):
    pass

pdf = CJKPDF()
pdf.add_page()

# Add CJK font - use simsun.ttc
font_path = r'C:\Windows\Fonts\simsun.ttc'
pdf.add_font('SimSun', '', font_path, uni=True)
pdf.set_font('SimSun', '', 12)

# Test text
test_text = '中文测试：收益率18.16%，年化2.75%，夏普0.76\n'
test_text += 'English: Sharpe=0.76, Layer 1, DISTRIB 81.62%\n'
test_text += 'This is a test of CJK PDF generation with Chinese characters.\n'
test_text += '收益矩阵：MEDIUM×TREND_UP最佳，Sharpe 0.62\n'
test_text += '资本效率：利用率27.9%，闲置72.1%\n'

for line in test_text.split('\n'):
    pdf.cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")

# Add a table
pdf.ln(5)
pdf.set_font('SimSun', '', 10)
pdf.cell(0, 10, '综合绩效指标', new_x="LMARGIN", new_y="NEXT")
pdf.set_font('SimSun', '', 9)

col_w = [60, 60]
headers = ['指标', '值']
data = [
    ['总收益率', '18.16%'],
    ['年化收益率', '2.75%'],
    ['总交易次数', '88（买入44/卖出44）'],
    ['最大回撤', '2.38%'],
    ['Calmar比率', '1.15'],
]

for i, h in enumerate(headers):
    pdf.cell(col_w[i], 8, h, border=1, align='C')
pdf.ln()

for row in data:
    for i, cell in enumerate(row):
        pdf.cell(col_w[i], 8, cell, border=1, align='C')
    pdf.ln()

# Save
test_path = r'C:\Users\17699\mozhi_platform\reports\pdf\_fpdf_test.pdf'
pdf.output(test_path)
print(f'[OK] Generated: {test_path}')
print(f'Size: {os.path.getsize(test_path):,} bytes')

# Verify with pdfminer
from pdfminer.high_level import extract_text
text = extract_text(test_path)
print(f'\nExtracted text:')
print(text[:500])

cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
print(f'\nCJK chars: {cn}')
expected = '中文测试'
print(f'Expected "{expected}" found: {expected in text}')
expected2 = '收益率'
print(f'Expected "{expected2}" found: {expected2 in text}')
expected3 = 'Sharpe'
print(f'Expected "{expected3}" found: {expected3 in text}')
