"""入口脚本：调用 pytest.main()，生成 HTML 报告到 test_results 目录"""

import sys
import os
from pathlib import Path

# 确保在项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)

# 确保 src 可导入
sys.path.insert(0, str(PROJECT_ROOT))

# 创建测试结果目录
results_dir = PROJECT_ROOT / "test_results"
results_dir.mkdir(exist_ok=True)

import pytest

if __name__ == "__main__":
    html_report = results_dir / "report.html"
    exit_code = pytest.main([
        "--html", str(html_report),
        "--self-contained-html",
    ])
    sys.exit(exit_code)
