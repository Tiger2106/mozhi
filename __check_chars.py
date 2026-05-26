import sys, io, tempfile, os

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
with open(path, 'rb') as f:
    content = f.read()

text = content.decode('utf-8')

# Get line 173
lines = text.split('\n')
line173 = lines[172]
print(f'Line 173 repr: {repr(line173)}')
print(f'Line 173 chars: ', end='')
for c in line173:
    print(f'U+{ord(c):04X} ', end='')
print()

# Now compare with what we'd expect
# Expected: '    """查询指定账户的订单成交状态，生成结构化报告"""'
# That's: 4 spaces + """ + 查询指定账户的订单成交状态 + ， + 生成结构化报告 + """
expected_chars = list('\u67e5\u8be2\u6307\u5b9a\u8d26\u6237\u7684\u8ba2\u5355\u6210\u4ea4\u72b6\u6001\uff0c\u751f\u6210\u7ed3\u6784\u5316\u62a5\u544a')
print(f'Expected chars ({len(expected_chars)}): ', end='')
for c in expected_chars:
    print(f'U+{ord(c):04X} ', end='')
print()
