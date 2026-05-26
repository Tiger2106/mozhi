# encoding: utf-8
import sys

# Test with the exact problematic character (fullwidth comma U+FF0C)
# Using unicode escapes to avoid shell/encoding issues
line = 'x = """\u67e5\u8be2\u6307\u5b9a\u8d26\u6237\u7684\u8ba2\u5355\u6210\u4ea4\u72b6\u6001\uff0c\u751f\u6210\u7ed3\u6784\u5316\u62a5\u544a"""'
print(f'Test line: {repr(line)}')
try:
    code = compile(line + '\n', '<test>', 'exec')
    print('Compiled OK')
    exec(code)
    print(f'x = {x}')
except SyntaxError as e:
    print(f'SyntaxError: {e}')
except Exception as e:
    print(f'Runtime error: {e}')
print(f'Python: {sys.version}')
