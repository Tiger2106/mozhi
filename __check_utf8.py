import sys

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'rb') as f:
    content = f.read()

# Check for any bytes that are NOT valid UTF-8
# Let's find issues
i = 0
errors = []
while i < len(content):
    byte = content[i]
    if byte < 0x80:
        i += 1
    elif 0xC2 <= byte <= 0xDF:
        if i+1 >= len(content) or (content[i+1] & 0xC0) != 0x80:
            errors.append(i)
        i += 2
    elif 0xE0 <= byte <= 0xEF:
        if i+2 >= len(content) or (content[i+1] & 0xC0) != 0x80 or (content[i+2] & 0xC0) != 0x80:
            errors.append(i)
        i += 3
    elif 0xF0 <= byte <= 0xF4:
        if i+3 >= len(content) or (content[i+1] & 0xC0) != 0x80 or (content[i+2] & 0xC0) != 0x80 or (content[i+3] & 0xC0) != 0x80:
            errors.append(i)
        i += 4
    else:
        errors.append(i)
        i += 1

if errors:
    print(f'Found {len(errors)} invalid byte positions')
    for pos in errors[:10]:
        context = content[max(0,pos-5):pos+5]
        print(f'  Position {pos}: byte 0x{content[pos]:02x} context: {context.hex()}')
else:
    print('All bytes are valid UTF-8')
