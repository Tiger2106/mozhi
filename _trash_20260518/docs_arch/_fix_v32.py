#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fix remaining issues in v3.2 document"""
import sys

path = r'C:\Users\17699\mozhi_platform\docs\01_architecture\pdf_report_design_v3.0_20260517.md'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
for i, line in enumerate(lines):
    if '7.8' in line and ('调用' in line or '调用' in line):
        print(f'Found §7.8 at line {i+1}: {line}')
    if '7.9' in line and 'Portfolio' in line:
        print(f'Found §7.9 at line {i+1}: {line}')
    if '7.10' in line:
        print(f'Found §7.10 at line {i+1}: {line}')
    if '快速启动' in line and '## 8' in line:
        print(f'Found §8 at line {i+1}: {line}')
    if 'v3.2' in line and '风险' in line:
        print(f'Found footer marker at line {i+1}: {line}')
    if '本文档由' in line:
        print(f'Found footer at line {i+1}: {line}')
