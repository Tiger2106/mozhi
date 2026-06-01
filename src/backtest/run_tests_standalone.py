"""
Standalone test runner for price_boundary tests.
Bypasses pytest/pdb Python 3.14 compatibility issue.
"""
import sys
import os
import unittest

# Add backtest_engine to path
sys.path.insert(0, r"C:\Users\17699\mo_zhi_sharereports")
os.chdir(r"C:\Users\17699\mozhi_platform\src\backtest")

from price_boundary_tests_suite import create_test_suite

suite = create_test_suite()
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)

# Return exit code based on test results
sys.exit(0 if result.wasSuccessful() else 1)
