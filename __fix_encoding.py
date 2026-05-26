#!/usr/bin/env python3
"""Fix encoding issues in check_orders_fill.py"""
import re

path = r'C:\Users\17699\mozhi_platform\src\trading\core\check_orders_fill.py'
out_path = path  # overwrite

with open(path, 'rb') as f:
    content = f.read()

# Decode as UTF-8, replacing all errors
text = content.decode('utf-8', errors='replace')

# Remove all replacement characters (U+FFFD) from comments/docstrings
# Strategy: replace the replacement char with nothing
text = text.replace('\ufffd', '')

# Also check for any other problematic characters
# U+FF0C (fullwidth comma) should be fine in Python, but let's check
# Let's just write back and try
with open(out_path, 'w', encoding='utf-8') as f:
    f.write(text)

print('Fixed encoding')
