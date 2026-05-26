#!/usr/bin/env python3
"""Test CJK PDF with fpdf2 without deprecated API."""
import os
from fpdf import FPDF
from pdfminer.high_level import extract_text

pdf = FPDF()
pdf.add_page()

# Use fpdf2's native CJK support
font_path = r'C:\Windows\Fonts\simsun.ttc'
pdf.add_font('SimSun', '', font_path)
pdf.set_font('SimSun', '', 12)

lines = [
    ('中文测试：收益率18.16%，年化2.75%，夏普0.76', 0),
    ('English: Sharpe=0.76, Layer 1, DISTRIB 81.62%', 0),
    ('收益矩阵：MEDIUM×TREND_UP最佳，Sharpe 0.62', 0),
    ('资本效率：利用率27.9%，闲置72.1%', 0),
    ('假突破分析：突破909次，假突破119次（13.09%）', 0),
    ('生命周期：DISTRIB 81.6%，PRE_INIT 16.3%', 0),
    ('最大回撤 2.38%，Calmar比率 1.15', 0),
]
for text, _ in lines:
    pdf.multi_cell(0, 8, text)

# Save
test_path = r'C:\Users\17699\mozhi_platform\reports\pdf\_fpdf_test2.pdf'
pdf.output(test_path)
print(f'[OK] Generated: {test_path}')
print(f'Size: {os.path.getsize(test_path):,} bytes')

# Check raw PDF
with open(test_path, 'rb') as f:
    raw = f.read()

# Look for CJK references
import re
for m in re.finditer(rb'/BaseFont\s+/\S+', raw):
    print(f'  BaseFont: {m.group().decode("latin-1")}')
for m in re.finditer(rb'/FontName\s+/\S+', raw):
    print(f'  FontName: {m.group().decode("latin-1")}')

ff2 = raw.count(b'/FontFile2')
print(f'  FontFile2 streams: {ff2}')
print(f'  Total size: {len(raw)} bytes')

# Try pikepdf if available
try:
    import pikepdf
    with pikepdf.open(test_path) as pdf_file:
        pages = len(pdf_file.pages)
        print(f'\npikepdf: {pages} page(s)')
        # Check fonts
        for i, page in enumerate(pdf_file.pages):
            if '/Resources' in page and '/Font' in page['/Resources']:
                fonts = page['/Resources']['/Font']
                for name, font in fonts.items():
                    print(f'  Page {i+1}: Font {name} = {font["/Subtype"]}, BaseFont={font["/BaseFont"]}')
except ImportError:
    print('\npikepdf not available')
    # Try pypdf
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(test_path)
        print(f'\nPyPDF2: {len(reader.pages)} page(s)')
        for i, page in enumerate(reader.pages[:1]):
            print(f'  Page {i+1}: {page.extract_text()[:100]}')
    except ImportError:
        print('No alternative PDF parser')

# pdfminer extraction
text = extract_text(test_path)
cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
print(f'\npdfminer: CJK chars={cn}')
print(f'  Sample: {repr(text[:200])}')
