"""Check encoding of report_builder.py."""
with open(r'C:\Users\17699\mozhi_platform\src\backtest\pipeline\report_builder.py', 'rb') as f:
    raw = f.read()

# Check for BOM
print(f"Has BOM: {raw[:3]}")

# Find around "Regime"
idx = raw.find(b'Regime')
if idx > 0:
    chunk = raw[idx:idx+80]
    print(f"Bytes: {chunk.hex(' ')}")
    try:
        decoded = chunk.decode('utf-8')
        print(f"UTF-8: {repr(decoded)}")
    except:
        print("NOT valid UTF-8!")
        # Try gbk
        try:
            decoded = chunk.decode('gbk')
            print(f"GBK: {repr(decoded)}")
        except:
            print("Also not GBK")

# Count how many lines
lines = raw.split(b'\n')
print(f"\nTotal lines: {len(lines)}")

# Check line 837
if len(lines) >= 837:
    line = lines[836]  # 0-indexed
    print(f"Line 837 raw: {line.hex(' ')}")
    try:
        print(f"Line 837 UTF-8: {line.decode('utf-8')[:100]}")
    except:
        # Try GBK
        print(f"Line 837 is not UTF-8!")
