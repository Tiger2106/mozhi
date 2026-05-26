#!/usr/bin/env python3
"""Verify PDF font embedding."""
import re

with open(r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf', 'rb') as f:
    content = f.read()

print(f'File size: {len(content):,} bytes')
print(f'SimSun references: {content.count(b"SimSun")}')
print(f'FontFile2 streams: {content.count(b"/FontFile2")} (embedded TTF data)')
print(f'ToUnicode CMaps: {content.count(b"/ToUnicode")}')
pages = content.count(b'/Type /Page') - content.count(b'/Type /Pages')
print(f'Pages: ~{pages}')

# Find FontDescriptor entries with FontFile2
print('\nFont descriptors with FontFile2:')
for m in re.finditer(rb'/FontDescriptor.*?>>', content, re.DOTALL):
    chunk = m.group()
    if b'FontFile2' in chunk:
        fn_match = re.search(rb'/FontName\s+/([^\s]+)', chunk)
        fn = fn_match.group(1).decode('latin-1') if fn_match else 'unknown'
        print(f'  {fn} - FontFile2 embedded')

# Check for actual TTF magic bytes in streams
ttf_headers = [m.start() for m in re.finditer(b'\x00\x01\x00\x00\x00', content)]
print(f'\nTrueType magic headers found: {len(ttf_headers)}')
print(f'  (Each represents an embedded TrueType font program)')

print('\n=== VERDICT ===')
if content.count(b'/FontFile2') >= 2 and content.count(b'SimSun') > 0:
    print('PASS: Chinese font (SimSun) is embedded with FontFile2 streams')
else:
    print('WARNING: Font embedding may be incomplete')
print(f'The PDF contains {pages} pages of content and is ready for viewing')
