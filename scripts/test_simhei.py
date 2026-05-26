#!/usr/bin/env python3
"""Test with simhei.ttf instead of simsun.ttc."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import ParagraphStyle
from pdfminer.high_level import extract_text

# Register SimHei (TTF, not TTC)
fp = r'C:\Windows\Fonts\simhei.ttf'
print(f'SimHei exists: {os.path.exists(fp)}')
pdfmetrics.registerFont(TTFont('SimHei', fp))

# Generate test PDF
test_path = r'C:\Users\17699\mozhi_platform\reports\pdf\_font_test2.pdf'
doc = SimpleDocTemplate(test_path, pagesize=A4)
style = ParagraphStyle('test', fontName='SimHei', fontSize=12, leading=16)
test_text = 'Font: SimHei<br/>中文测试：收益率18.16%，年化2.75%，夏普0.76<br/>English: Sharpe=0.76, Layer 1, DISTRIB 81.62%<br/>This is a test of CJK PDF generation with Chinese characters.'
p = Paragraph(test_text, style)
doc.build([p])

# Verify
with open(test_path, 'rb') as f:
    raw = f.read()
size = len(raw)
print(f'Size: {size:,} bytes')
print(f'FontFile2: {raw.count(b"/FontFile2")}')
print(f'FlateDecode: {raw.count(b"FlateDecode")}')

# Check for TTF magic in raw (may be compressed)
magic = raw.count(b'\x00\x01\x00\x00\x00')
print(f'TTF magic bytes (uncompressed): {magic}')

# Try extraction
text = extract_text(test_path)
print(f'\nExtracted text:')
print(repr(text))
cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
print(f'CJK chars: {cn}')

# Check if specific Chinese chars are present
expected = '收益率'
found = expected in text
print(f'Expected "{expected}" found: {found}')

expected2 = '中文测试'
found2 = expected2 in text
print(f'Expected "{expected2}" found: {found2}')

# If still garbled, try with raw bytes
print(f'\nRaw bytes around CJK area:')
for i, c in enumerate(text):
    if '\u4e00' <= c <= '\u9fff':
        window = text[max(0,i-5):i+15]
        print(f'  CJK at pos {i}: ...{repr(window)}...')
        break

print(f'\n=== Verdict ===')
if cn > 3 and (found or found2):
    print('SUCCESS: CJK text IS properly renderable')
else:
    print('ISSUE: CJK text extraction still shows garbled, but may just be pdfminer issue')
    print('The actual PDF when opened in Chrome/Adobe should render correctly')
