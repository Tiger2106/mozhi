#!/usr/bin/env python3
"""Deep check CJK PDF: decompress streams and verify CMap."""

import re, zlib

with open(r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf', 'rb') as f:
    raw = f.read()

# Find and decompress all FlateDecode streams
print('=== Decompressing PDF streams ===')
obj_starts = [m.start() for m in re.finditer(rb'(\d+)\s+\d+\s+obj', raw)]
obj_data = {}
for i, start in enumerate(obj_starts):
    try:
        end = obj_starts[i+1] if i+1 < len(obj_starts) else len(raw)
    except:
        end = len(raw)
    block = raw[start:end]
    
    # Get object number
    obj_match = re.match(rb'(\d+)\s+\d+\s+obj', raw[start:])
    if obj_match:
        obj_num = int(obj_match.group(1))
    else:
        continue
    
    # Find stream
    sm = re.search(rb'stream\s(.+?)\n?endstream', block, re.DOTALL)
    if sm:
        stream_data = sm.group(1).strip()
        if b'FlateDecode' in block:
            try:
                decompressed = zlib.decompress(stream_data)
                obj_data[obj_num] = decompressed
                if stream_data[:10] != raw[start+sm.start()+7:start+sm.start()+17]:
                    pass
            except:
                pass

print(f'Decompressed {len(obj_data)} streams')

# Find ToUnicode CMap objects
for obj_num, data in obj_data.items():
    if b'CMap' in data[:50]:
        print(f'\n=== ToUnicode CMap (Object {obj_num}) ===')
        print(data.decode('latin-1')[:500])

# Find content streams to check actual text
for obj_num, data in obj_data.items():
    if data.startswith(b'BT') or b'/F1' in data[:100] or b'Tj' in data:
        print(f'\n=== Content Stream (Object {obj_num}) - first 500 bytes ===')
        print(data[:500].decode('latin-1'))
        print('...')
        break

# Check SimSun font descriptor
for obj_num, data in obj_data.items():
    if b'SimSun' in data:
        print(f'\n=== SimSun font data (Object {obj_num}) ===')
        print(data[:300].decode('latin-1'))

print('\n=== Verification Summary ===')
print(f'Total PDF size: {len(raw):,} bytes')
pages = raw.count(b'/Type /Page') - raw.count(b'/Type /Pages')
print(f'Pages: ~{pages}')
print(f'FlateDecode streams: {len(obj_data)} decompressed')
print(f'ToUnicode CMaps found: {sum(1 for d in obj_data.values() if b"CMap" in d[:50])}')
