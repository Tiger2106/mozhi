#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成验证脚本 — 管线集成测试
============================
测试内容：完整管线（数据管线 + 信号管线）端到端验证。
 
测试步骤：
  1. 导入验证：确认所有模块 import 路径正确
  2. 数据管线：对已知标的手动计算日频因子
  3. 信号管线：对分钟级数据模拟计算
  4. 编排器：验证全管线结果合并
  5. 回测兼容性：confirm import 方式

作者: 墨衡 (moheng)
日期: 2026-05-22
"""

import sys
import os
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("test_integration")

# ── 环境准备 ──────────────────────────────────────────────

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(PROJECT_ROOT))  # 保证 import backtest_engine 生效

PASS = "✅ PASS"
FAIL = "❌ FAIL"
SKIP = "⏭️  SKIP"

passed = 0
failed = 0
skipped = 0


def check(name: str, condition: bool, detail: str = ""):
    global passed, failed
    if condition:
        logger.info("%s | %s %s", PASS, name, detail)
        passed += 1
    else:
        logger.error("%s | %s %s", FAIL, name, detail)
        failed += 1


def skip(name: str, reason: str = ""):
    global skipped
    logger.warning("%s | %s %s", SKIP, name, reason)
    skipped += 1


# ═══════════════════════════════════════════════════════════
# Step 1: Import 验证
# ═══════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("Step 1: Import 验证")
logger.info("=" * 60)

# 1a. 数据管线模块
try:
    from backtest_engine.pipeline import DataPipeline, SignalPipeline, PipelineOrchestrator, run_pipeline
    check("pipeline 模块导入", True, "DataPipeline, SignalPipeline, PipelineOrchestrator, run_pipeline")
except ImportError as e:
    check(f"pipeline 模块导入: {e}", False)

# 1b. calc 模块
try:
    from backtest_engine.calc import (
        FloatShareCache,
        calc_turnover_rate,
        calc_volume_ratio,
        VWAPChannel,
        calc_volume_skewness,
        calc_volume_price_corr,
        calc_gini_coefficient,
        calc_hhi,
    )
    check("calc 模块全部导入", True, f"{len([x for x in [FloatShareCache, calc_turnover_rate, calc_volume_ratio, VWAPChannel, calc_volume_skewness, calc_volume_price_corr, calc_gini_coefficient, calc_hhi] if x])} 个模块")
except ImportError as e:
    check(f"calc 模块导入: {e}", False)

# 1c. collector 模块
try:
    from backtest_engine.collector import MinuteCollector
    check("collector 模块导入", True)
except ImportError as e:
    check(f"collector 模块导入: {e}", False)

# 1d. data_ingestion 模块
try:
    from backtest_engine.data_ingestion import data_contract, etl_normalizer
    check("data_ingestion 模块导入", True)
except ImportError as e:
    check(f"data_ingestion 模块导入: {e}", False)


# ═══════════════════════════════════════════════════════════
# Step 2: calc 模块单元测试（无 DB 依赖）
# ═══════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("Step 2: calc 模块单元测试（无 DB 依赖）")
logger.info("=" * 60)

# 2a. 换手率
tr = calc_turnover_rate(amount=1_020_000_000, float_share=1_619_220_778, price=10.68)
check("calc_turnover_rate", tr is not None and 0 <= tr <= 1, f"值={tr:.6f}")

# 2b. 量比
vr = calc_volume_ratio(current_vol=100_000_000, ma_vol=80_000_000)
check("calc_volume_ratio", vr is not None and vr > 0, f"值={vr:.4f}")

# 2c. VWAPChannel（无 DB 的单元级方法）
vwap_calc = VWAPChannel(db_path=":memory:").calc_avg_trade_price(amount=10_000_000, volume=1_000_000)
check("calc_avg_trade_price", vwap_calc == 10.0, f"值={vwap_calc}")

# 2d. 量偏度
from backtest_engine.calc.volume_skewness import calc_volume_skewness, classify_skewness
vols = [100 + i * 10 for i in range(48)]  # 模拟均匀分布
skew = calc_volume_skewness(vols)
check("calc_volume_skewness", skew is not None, f"值={skew}")
check("classify_skewness(uniform)", classify_skewness(0.0) == 'uniform', f"label={classify_skewness(0.0)}")

# 2e. 量价相关系数
from backtest_engine.calc.volume_price_corr import calc_volume_price_corr, classify_correlation
vols_up = [100] * 48
prices_up = [10 + i * 0.02 for i in range(48)]  # 缓慢上涨
corr = calc_volume_price_corr(vols_up, prices_up)
check("calc_volume_price_corr", corr is not None, f"值={corr:.4f}")

# 2f. 量集中度
hhi = calc_hhi(vols)
gini = calc_gini_coefficient(vols)
check("calc_hhi", hhi is not None and hhi > 0, f"值={hhi}")
check("calc_gini_coefficient", gini is not None, f"值={gini}")

# 2g. FloatShareCache（不带远程调用）
cache = FloatShareCache(auto_init=False)
check("FloatShareCache 初始化", True, "no exceptions")


# ═══════════════════════════════════════════════════════════
# Step 3: SignalPipeline 分钟级因子计算（纯内存模式）
# ═══════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("Step 3: SignalPipeline 分钟级因子模拟")
logger.info("=" * 60)

# 模拟 48 条 5min K 线（一天 4h = 240min / 5 = 48 条）
import random
random.seed(42)

mock_minute_data = []
base_price = 10.50
for i in range(48):
    vol = int(random.uniform(500_000, 2_000_000))
    price_change = random.uniform(-0.05, 0.05)
    close_price = round(base_price + price_change, 2)
    mock_minute_data.append({
        'minute': f"{i // 12:02d}:{(i % 12) * 5:02d}",
        'close': close_price,
        'volume': vol,
        'amount': vol * close_price,
    })
    base_price = close_price

volumes = [r['volume'] for r in mock_minute_data]
prices = [r['close'] for r in mock_minute_data]

# 3a. 量偏度
skew2 = calc_volume_skewness(volumes)
check("Signal: volume_skewness", skew2 is not None, f"值={skew2}")

# 3b. 量价相关系数
corr2 = calc_volume_price_corr(volumes, prices)
check("Signal: volume_price_corr", corr2 is not None, f"值={corr2:.4f}")

# 3c. 量集中度
hhi2 = calc_hhi(volumes)
gini2 = calc_gini_coefficient(volumes)
check("Signal: HHI", hhi2 is not None, f"值={hhi2}")
check("Signal: Gini", gini2 is not None, f"值={gini2}")


# ═══════════════════════════════════════════════════════════
# Step 4: PipelineOrchestrator — 完整管线（基于已知 DB）
# ═══════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("Step 4: PipelineOrchestrator 完整管线（基于分析库现有数据）")
logger.info("=" * 60)

# 尝试连接已有 analysis.db
import sqlite3

ANALYSIS_DB = os.path.join(
    os.environ.get("MOZHIHOME", r"C:\Users\17699\mo_zhi_sharereports"),
    "analysis.db"
)

if os.path.exists(ANALYSIS_DB):
    # 查看是否有可用数据
    conn = sqlite3.connect(ANALYSIS_DB)
    cur = conn.cursor()
    try:
        cur.execute("SELECT code, date FROM stock_daily LIMIT 1")
        sample = cur.fetchone()
        if sample:
            test_code = sample[0] if '.' not in sample[0] else sample[0].split('.')[0]
            test_date = str(sample[1]) if not sample[1].isdigit() else str(sample[1])

            # 运行完整管线
            orch = PipelineOrchestrator(db_path=ANALYSIS_DB)
            full_result = orch.run_full(test_code, test_date, include_signal=True)
            
            dp = full_result.get('data_pipeline', {})
            fs = full_result.get('factors_summary', {})
            
            check(f"完整管线运行 {test_code} {test_date}",
                  dp is not None and dp.get('close') is not None,
                  f"收盘价={dp.get('close')}")
            
            check("管线结果包含 float_share",
                  'float_share' in fs, f"值={fs.get('float_share')}")
            check("管线结果包含 turnover_rate",
                  'turnover_rate' in fs, f"值={fs.get('turnover_rate')}")
            check("管线结果包含 volume_ratio_ma20",
                  'volume_ratio_ma20' in fs, f"键存在")
            # VWAP 需要至少 3 个交易日数据；若不足则为 None 属于预期行为
            if fs.get('vwap') is not None:
                check("管线结果包含 vwap 值", True, f"值={fs.get('vwap')}")
            else:
                skip("管线结果 vwap", "测试数据不足 3 个交易日（预期行为，非故障）")
            
            # 信号管线结果（可能有或没有分钟数据）
            sp = full_result.get('signal_pipeline', {})
            if sp.get('minute_record_count', 0) > 0:
                check("信号管线包含 volume_skewness",
                      'volume_skewness' in fs,
                      f"值={fs.get('volume_skewness')}")
                check("信号管线包含 volume_price_corr",
                      'volume_price_corr' in fs,
                      f"值={fs.get('volume_price_corr')}")
                check("信号管线包含 volume_concentration_hhi",
                      'volume_concentration_hhi' in fs,
                      f"值={fs.get('volume_concentration_hhi')}")
            else:
                skip("信号管线因子", "analysis.db 中无分钟数据——如需验证请先运行 MinuteCollector")
        else:
            skip("完整管线", "analysis.db 中 stock_daily 表为空")
    except Exception as e:
        check(f"完整管线运行异常: {e}", False)
    finally:
        conn.close()
else:
    skip("完整管线", f"analysis.db 不存在于 {ANALYSIS_DB}")


# ═══════════════════════════════════════════════════════════
# Step 5: 回测导入兼容性验证
# ═══════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info("Step 5: 回测导入兼容性验证")
logger.info("=" * 60)

# 验证回测引擎可以 import pipeline 作为整体使用
try:
    from backtest_engine import pipeline as bt_pipeline
    check("from backtest_engine import pipeline", True)
except ImportError as e:
    check(f"from backtest_engine import pipeline: {e}", False)

# 验证快捷函数
try:
    from backtest_engine.pipeline import run_pipeline
    check("from backtest_engine.pipeline import run_pipeline", True)
except ImportError as e:
    check(f"快捷导入: {e}", False)

# 验证 calc 子模块可以单独导入
try:
    from backtest_engine.calc import turnover_rate, volume_ratio, vwap_channel
    check("calc 子模块单独导入 (turnover_rate, volume_ratio, vwap_channel)", True)
except ImportError as e:
    check(f"calc 子模块导入: {e}", False)

try:
    from backtest_engine.calc import volume_skewness, volume_price_corr, volume_concentration
    check("calc 信号因子单独导入 (volume_skewness, volume_price_corr, volume_concentration)", True)
except ImportError as e:
    check(f"calc 信号因子导入: {e}", False)


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════

logger.info("=" * 60)
logger.info(f"测试汇总: {passed} PASS, {failed} FAIL, {skipped} SKIP")
logger.info("=" * 60)

if failed > 0:
    logger.error("有 %d 个测试失败，请检查日志。", failed)
    sys.exit(1)
else:
    logger.info("所有核心测试通过！管线集成验证完成。")
    sys.exit(0)
