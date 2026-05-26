#!/usr/bin/env python3
"""Deep inspect PDF font embedding."""
import re, zlib

with open(r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf', 'rb') as f:
    content = f.read()

# Find all FontFile2 object references
for m in re.finditer(rb'(\d+)\s+\d+\s+obj', content):
    start = m.start()
    obj_header = m.group()
    # Get the object content
    try:
        end = content.index(b'endobj', start)
        block = content[start:end]
    except:
        continue
    
    if b'/FontFile2' in block:
        obj_num = m.group(1).decode()
        # Find the stream length
        len_match = re.search(rb'/Length\s+(\d+)', block)
        stream_len = int(len_match.group(1)) if len_match else 0
        print(f'Object {obj_num} - FontFile2 stream, declared length: {stream_len}')
        
        # Find stream data
        stream_start = block.find(b'stream\n')
        if stream_start >= 0:
            raw_start = stream_start + 7  # len of 'stream\n'
            raw_data = block[raw_start:raw_start+min(100, stream_len)]
            print(f'  First bytes (hex): {raw_data[:20].hex()}')
            # Check if it's compressed
            print(f'  Filter: {"FlateDecode" if b"FlateDecode" in block else "none"}')
    elif b'/Font' in block and b'/Subtype' in block:
        # Check for font references
        fn_match = re.search(rb'/BaseFont\s+/\S+', block)
        if fn_match:
            fn = fn_match.group().decode('latin-1')
            desc_match = re.search(rb'/FontDescriptor\s+(\d+)', block)
            desc_num = desc_match.group(1).decode() if desc_match else '?'
            print(f'Font obj {obj_num}: {fn} -> FontDescriptor {desc_num}')

print('\n=== Checking raw font descriptor objects ===')
for m in re.finditer(rb'(\d+)\s+\d+\s+obj', content):
    start = m.start()
    obj_header = m.group()
    try:
        end = content.index(b'endobj', start)
        block = content[start:end]
    except:
        continue
    
    if b'/FontDescriptor' in block and b'/FontName' in block:
        fn_match = re.search(rb'/FontName\s+/(\S+)', block)
        ff2_match = re.search(rb'/FontFile2\s+(\d+)', block)
        fn = fn_match.group(1).decode('latin-1') if fn_match else '?'
        ff2 = ff2_match.group(1).decode() if ff2_match else 'NONE'
        print(f'  Descriptor: FontName={fn}, FontFile2 stream obj={ff2}')
        
        # Check if FontFile2 stream has data
        if ff2_match:
            ff2_obj = ff2_match.group(1).decode()
            # Find stream object
            obj_pattern = rf'\n{ff2_obj}\s+\d+\s+obj'.encode()
            om = re.search(obj_pattern, content)
            if om:
                try:
                    oend = content.index(b'endobj', om.start())
                    oblock = content[om.start():oend]
                    len_m = re.search(rb'/Length\s+(\d+)', oblock)
                    if len_m:
                        print(f'    Stream data length: {len_m.group(1).decode()} bytes')
                    # Check if it has TrueType header
                    sstart = oblock.find(b'stream\n')
                    if sstart >= 0:
                        raw = oblock[sstart+7:sstart+17]
                        print(f'    Stream first bytes hex: {raw.hex()}')
                except:
                    pass
