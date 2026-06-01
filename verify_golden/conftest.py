"""
verify_golden conftest.py — WI4 Golden Sample pytest fixtures
================================================================
Provides golden_samples (all), golden_sample (parametrized),
expected_output helper, and expected_fields fixture.

Author: moheng
Created: 2026-06-01T16:16:00+08:00
"""

import json
import os
import sqlite3

import pytest
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden_samples.json"

# 双模式 DB fixture 路径
DB_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_samples():
    """Load and cache golden samples from disk."""
    with open(GOLDEN_DIR, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------


def _setup_mock_schema(conn: sqlite3.Connection) -> None:
    """在 mock DB 中创建必要的表结构（与真实 DB 一致）。"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS a50_universe (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code         TEXT    NOT NULL,
            stock_name      TEXT,
            in_date         TEXT    NOT NULL,
            out_date        TEXT,
            weight          REAL,
            source          TEXT    NOT NULL DEFAULT 'tushare',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(ts_code, in_date)
        );

        CREATE TABLE IF NOT EXISTS a50_daily_ohlcv (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code         TEXT    NOT NULL,
            trade_date      TEXT    NOT NULL,
            open            REAL,
            high            REAL,
            low             REAL,
            close           REAL,
            pre_close       REAL,
            volume          REAL,
            amount          REAL,
            turnover_rate   REAL,
            pe              REAL,
            pb              REAL,
            adj_factor      REAL    NOT NULL,
            null_reason     TEXT,
            float_share     REAL,
            total_share     REAL,
            source_version  TEXT    NOT NULL DEFAULT 'v1',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            adj_close_b     REAL,
            adj_open_b      REAL,
            adj_high_b      REAL,
            adj_low_b       REAL,
            adj_pre_close_b REAL,
            pe_ttm          REAL,
            ps_ttm          REAL,
            pcf_ttm         REAL,
            dividend_yield  REAL,
            ps_ttm_category TEXT
        );

        CREATE TABLE IF NOT EXISTS a50_daily_basic (
            code            TEXT    NOT NULL,
            date            TEXT    NOT NULL,
            pe              REAL,
            pe_ttm          REAL,
            pb              REAL,
            ps_ttm          REAL,
            float_share     REAL,
            total_share     REAL,
            circ_mv         REAL,
            source_version  TEXT    NOT NULL DEFAULT 'v1',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            dividend_yield  REAL,
            PRIMARY KEY (code, date)
        );

        CREATE TABLE IF NOT EXISTS a50_cross_ic_result (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date      TEXT    NOT NULL,
            factor_name     TEXT    NOT NULL,
            ic_value        REAL,
            rank_ic         REAL,
            p_value         REAL,
            num_stocks      INTEGER NOT NULL,
            adjusted_ic     REAL,
            forward_window  INTEGER NOT NULL DEFAULT 5,
            source_version  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(trade_date, factor_name, source_version, forward_window)
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_connection(request, tmp_path_factory):
    """双模式 DB fixture。

    默认：mock 模式，在 temp 目录创建临时 DB（不含数据，仅表结构），
          适合 CI 无真实 DB 环境。

    真实模式：设置环境变量 ``VERIFY_DB_REAL=1``，将直接连接
              ``data/market/a50_ic.db`` 读取真实数据。
    """
    if os.environ.get("VERIFY_DB_REAL") == "1":
        db_file = DB_DIR / "market" / "a50_ic.db"
        if not db_file.exists():
            pytest.skip(f"Real DB not found: {db_file}")
        conn = sqlite3.connect(str(db_file))
    else:
        db_path = tmp_path_factory.mktemp("mock_db") / "test_ic.db"
        conn = sqlite3.connect(str(db_path))
        _setup_mock_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def golden_samples():
    """Return the full list of golden samples (3 entries).

    Each sample dict contains:
        id, description, scenario, market_context,
        input (start_date, end_date),
        expected_output (ic_mean_min/max, win_rate_min/max, turnover_min/max),
        rationale
    """
    data = _load_samples()
    return data["samples"]


@pytest.fixture(scope="session")
def golden_sample(request, golden_samples):
    """Parametrized fixture — returns a single golden sample by ``id``.

    Usage in a test function::

        @pytest.mark.parametrize("golden_sample", ["gs_bull_2023q2q3"], indirect=True)
        def test_something(golden_sample):
            ...

    Or combine with pytest_generate_tests / conftest-level parametrization.
    """
    sample_id = request.param
    for s in golden_samples:
        if s["id"] == sample_id:
            return s
    raise KeyError(f"Golden sample '{sample_id}' not found in golden_samples.json")


def pytest_generate_tests(metafunc):
    """Auto-parametrize ``golden_sample`` for every sample in the file.

    Any test function that declares a ``golden_sample`` parameter will
    receive it parametrized over all 3 sample IDs automatically.
    """
    if "golden_sample" in metafunc.fixturenames:
        data = _load_samples()
        ids = [s["id"] for s in data["samples"]]
        metafunc.parametrize("golden_sample", ids, indirect=True, ids=ids)


@pytest.fixture(scope="module")
def expected_fields():
    """Return the list of expected-output field names used by the pipeline.

    These fields appear in every sample's ``expected_output`` dict and are
    checked during regression verification.
    """
    return [
        "ic_mean_min",
        "ic_mean_max",
        "win_rate_min",
        "win_rate_max",
        "turnover_min",
        "turnover_max",
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def expected_output(sample: dict) -> dict:
    """Return the expected-output range dict from a golden sample.

    Shorthand for ``sample["expected_output"]`` with a None-safe guard:

    >>> sample = {"expected_output": {"ic_mean_min": 0.04, ...}}
    >>> eo = expected_output(sample)
    >>> assert 0.04 <= some_metric <= 0.15
    """
    return sample.get("expected_output", {})
