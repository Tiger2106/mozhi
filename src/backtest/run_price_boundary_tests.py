"""
Simple test runner for price_boundary tests.
Bypasses pytest debugging plugin issue on Python 3.14.
"""
import sys
import os

sys.path.insert(0, r"C:\Users\17699\mo_zhi_sharereports")
sys.path.insert(0, r"C:\Users\17699\mozhi_platform\src\backtest")
os.chdir(r"C:\Users\17699\mozhi_platform\src\backtest")

# Disable pytest debugging plugin via conftest override
import pytest
sys.exit(pytest.main([
    "-v",
    "--override-ini=addopts=",
    "-o", "required_plugins=",
    "-p", "no:debugging",
    "-p", "no:cacheprovider",
    "-p", "no:recwarn",
    "-p", "no:doctest",
    "-p", "no:unittest",
    "tests/test_price_boundary.py",
]))
