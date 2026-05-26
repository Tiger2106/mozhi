#!/usr/bin/env python3
"""Check test PDF content."""
import re, os
from pdfminer.high_level import extract_text

path = r'C:\Users\17699\mozhi_platform\reports\pdf\_font_test.pdf'
size = os.path.getsize(path)
print(f'Size: {size:,} bytes')

text = extract_text(path)
print(f'Extracted text:')
print(text)

cn = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
print(f'\nChinese characters: {cn}')

# Also check raw PDF for embedded font headers
with open(path, 'rb') as f:
    raw = f.read()

# Check for TrueType magic bytes
tt_headers = []
for i in range(len(raw)):
    if raw[i:i+4] == b'\x00\x01\x00\x00' and raw[i+4:i+5] == b'\x00':
        tt_headers.append(i)
        
print(f'TrueType magic headers: {len(tt_headers)}')

# Check FontFile2 content
if tt_headers:
    for pos in tt_headers[:2]:
        print(f'  TTF header at offset: {pos}')
        # Read the sfVersion
        print(f'  sfVersion: {raw[pos+4:pos+8].hex()}')
        # Number of tables
        num_tables = int.from_bytes(raw[pos+8:pos+10], 'big')
        print(f'  Num tables: {num_tables}')
else:
    # The stream might be compressed with FlateDecode
    print('No TTF magic - streams likely compressed (FlateDecode)')
    # In that case the FontFile2 stream IS embedded but compressed
    print('Checking for FontFile2 and FlateDecode...')
    print(f'  FontFile2: {raw.count(b"/FontFile2")}')
    print(f'  FlateDecode: {raw.count(b"FlateDecode")}')
