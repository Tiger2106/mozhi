#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Final fix: replace §7.8, add §7.10, update §8, update footer"""

path = r'C:\Users\17699\mozhi_platform\docs\01_architecture\pdf_report_design_v3.0_20260517.md'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace §7.8 - old v3.0 call example
# Find the exact range from "### 7.8" to "## 8."
idx_78 = content.index('### 7.8 \u8c03\u7528\u793a\u4f8b\uff08v3.0 \u5b8c\u6574\u7ba1\u9053\uff09')
idx_8 = content.index('## 8. \u5feb\u901f\u542f\u52a8\u6307\u5357\uff08\u4eca\u665a\uff09')

# Read content for a sample to show what's between
old_section = content[idx_78:idx_8]
print(f'Old section length: {len(old_section)} chars')
print(f'First 50 chars: {old_section[:50]}')
print(f'Last 50 chars: {old_section[-50:]}')

# Also check if there's already §7.10 content
if '### 7.10' in content:
    print('§7.10 already exists!')
else:
    print('§7.10 not found - need to add')

# Check §8.1
idx_81 = content.index('### 8.1 \u6267\u884c\u6e05\u5355')
idx_82 = content.index('### 8.2 \u9a8c\u6536\u6807\u51c6')
old_81 = content[idx_81:idx_82]
print(f'§8.1 length: {len(old_81)} chars')
print(f'§8.1 first 200: {old_81[:200]}')

# Check footer
idx_footer = content.index('*本文档由墨衡编写')
print(f'Footer: {content[idx_footer:]}')
