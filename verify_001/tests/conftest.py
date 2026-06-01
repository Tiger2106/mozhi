"""共享 fixture"""

import sys
from pathlib import Path

import pytest

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.generator import generate_prices
from src.config import CROSS_SECTIONS


@pytest.fixture
def prices():
    return generate_prices()


@pytest.fixture
def cross_sections():
    return CROSS_SECTIONS
