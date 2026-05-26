# Check SimHei font and CJK rendering
import struct, os

fp = r'C:\Windows\Fonts\simhei.ttf'
size = os.path.getsize(fp)
print(f'Font: {fp}')
print(f'Size: {size} bytes')

with open(fp, 'rb') as f:
    head = f.read(12)
    sfversion = struct.unpack('>I', head[:4])[0]
    num_tables = struct.unpack('>H', head[4:6])[0]
    
    sf_name = {0x00010000: 'TrueType v1.0', 0x74727565: 'TrueType', 0x4F54544F: 'OpenType'}
    print(f'SF Version: 0x{sfversion:08X} ({sf_name.get(sfversion, "?")})')
    print(f'Tables: {num_tables}')
    
    tables = {}
    for _ in range(num_tables):
        tag = f.read(4).decode('latin-1')
        chk = struct.unpack('>I', f.read(4))[0]
        off = struct.unpack('>I', f.read(4))[0]
        ln = struct.unpack('>I', f.read(4))[0]
        tables[tag] = (off, ln)
    
    # Check cmap for CJK support
    if 'cmap' in tables:
        off, ln = tables['cmap']
        f.seek(off)
        ver = struct.unpack('>H', f.read(2))[0]
        nsub = struct.unpack('>H', f.read(2))[0]
        print(f'\ncmap: version={ver}, subtable_count={nsub}')
        
        for i in range(nsub):
            plat = struct.unpack('>H', f.read(2))[0]
            enc = struct.unpack('>H', f.read(2))[0]
            sub_off = struct.unpack('>I', f.read(4))[0]
            print(f'  Subtable {i}: Platform={plat}, Encoding={enc}, offset={sub_off}')
    
    # Check if font covers CJK range
    # Check 'cmap' format 4 or 12 for CJK coverage
    print(f'\nFont tables: {", ".join(sorted(tables.keys()))}')

# Try rendering Chinese with matplotlib to test font
import matplotlib.font_manager as fm
fonts = [f.name for f in fm.fontManager.ttflist if 'hei' in f.name.lower() or 'sim' in f.name.lower()]
print(f'\nMatplotlib detected CJK fonts: {set(fonts)}')
