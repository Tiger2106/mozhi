#!/usr/bin/env python3
"""Validate generated PDF for CJK content."""
import os, re, sys

path = r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf'
size = os.path.getsize(path)
print(f"Size: {size:,} bytes")

with open(path, 'rb') as f:
    content = f.read()

# Check PDF structure
cid_fonts = content.count(b'/CIDFontType2')
print(f"CIDFontType2 entries: {cid_fonts}")

# Check for ToUnicode CMap (needed for CJK text extraction)
tounicode = content.count(b'/ToUnicode')
print(f"ToUnicode CMaps: {tounicode}")

# Check for font names
for name in [b'CJK', b'SimSun', b'STSong', b'Sun']:
    count = content.count(name)
    if count > 0:
        print(f"  Font ref '{name.decode()}' : {count}")

# Check for base font references
basefont = re.findall(rb'/BaseFont.*?\)', content)
for bf in basefont[:5]:
    print(f"  BaseFont: {bf.decode('latin-1')}")

# Count pages
page_count = content.count(b'/Type /Page') - content.count(b'/Type /Pages')
print(f"Pages: ~{page_count}")

# Try text extraction
try:
    import pdfminer.high_level
    text = pdfminer.high_level.extract_text(path, maxpages=3)
    cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    print(f"Chinese chars (pdfminer, page 1-3): {cn}")
    print(f"Sample: {text[:300]}")
except ImportError:
    print("pdfminer not available")

print("\n[OK] Validation complete")
print(f"File 1: {path}")
print(f"File 2: C:/Users/17699\\.openclaw\\workspace-mochen\\reports\\pdf\\601857_research_report_v2.1_20260518.pdf")
