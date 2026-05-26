#!/usr/bin/env python3
"""Test CJK font rendering and pick the best font."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Test each font with a simple PDF
fonts_to_test = {
    'SimSun-TTC': (r'C:\Windows\Fonts\simsun.ttc', 0),
    'SimSun-TTC1': (r'C:\Windows\Fonts\simsun.ttc', 1),
    'SimHei-TTF': (r'C:\Windows\Fonts\simhei.ttf', None),
    'MSYH-TTC': (r'C:\Windows\Fonts\msyh.ttc', 0),
    'MSYH-TTC1': (r'C:\Windows\Fonts\msyh.ttc', 1),
}

for name, (path, subfont) in fonts_to_test.items():
    try:
        if subfont is not None:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=subfont))
        else:
            pdfmetrics.registerFont(TTFont(name, path))
        print(f'[OK] {name}: registered from {os.path.basename(path)}, subfont={subfont}')
    except Exception as e:
        print(f'[FAIL] {name}: {e}')

# Now test which font works for PDF rendering
from reportlab.platypus import SimpleDocTemplate, Paragraph
from reportlab.lib.styles import ParagraphStyle

test_path = r'C:\Users\17699\mozhi_platform\reports\pdf\_font_test.pdf'
doc = SimpleDocTemplate(test_path, pagesize=A4)

for name in ['SimSun-TTC', 'MSYH-TTC']:
    try:
        style = ParagraphStyle('test', fontName=name, fontSize=12, leading=16)
        test_text = f'Font: {name}\n中文测试：收益率18.16%，年化2.75%，夏普0.76，最大回撤2.38%\nEnglish: Sharpe=0.76, Layer 1, DISTRIB 81.62%'
        p = Paragraph(test_text.replace('\n', '<br/>'), style)
        doc.build([p])
        print(f'[OK] Generated test PDF with {name}')
        break
    except Exception as e:
        print(f'[FAIL] Test with {name}: {e}')

# Check the test PDF
with open(test_path, 'rb') as f:
    content = f.read()
size = len(content)
print(f'\nTest PDF size: {size:,} bytes')
print(f'Contains Chinese chars: {"Chinese" in content.decode("latin-1", errors="ignore")}')
print(f'FontFile2 streams: {content.count(b"/FontFile2")}')
