"""
Phase 1 批次A — 契约四件套（B1-B16）完整单元测试

author: 墨衡
task_id: phase1_batchA_moheng
created_time: 2026-05-17 09:46 GMT+8
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict

import pandas as pd
import pytest

from src.backtest.methods.base import BaseMethod, MethodResult
from src.backtest.methods.manifest import (
    METHOD_META,
    validate_manifest,
    validate_factor_meta,
    FACTOR_META,
    MANIFEST_REQUIRED_FIELDS,
    CAPABILITIES_REQUIRED_FIELDS,
    FACTOR_META_REQUIRED_FIELDS,
)
from src.backtest.context import StrategyContext, RuntimeState
from src.backtest.factors.base import BaseFactor


# ══════════════════════════════════════════════════════════════════════
# B1 / B2: BaseMethod ABC — 抽象方法强制 + on_bar 默认行为
# ══════════════════════════════════════════════════════════════════════


class TestBaseMethodABC:
    """B1 + B2: BaseMethod 抽象方法不可实例化 + on_bar 默认 None。"""

    def test_cannot_instantiate_abstract(self):
        """直接实例化 BaseMethod 应抛 TypeError。"""
        with pytest.raises(TypeError):
            BaseMethod()  # type: ignore[abstract]  # 期望抛异常

    def test_subclass_must_implement_abstract(self):
        """缺少抽象方法的子类实例化时抛 TypeError。"""

        class MissingGenerateSignal(BaseMethod):
            def setup(self, ctx):
                pass

        with pytest.raises(TypeError):
            MissingGenerateSignal()

    def test_concrete_subclass_works(self):
        """完整实现所有抽象方法后可正常实例化。"""

        class ConcreteMethod(BaseMethod):
            def setup(self, ctx):
                self.ctx = ctx

            def generate_signal(self, df):
                return df

        m = ConcreteMethod()
        assert isinstance(m, BaseMethod)

    def test_on_bar_default_none(self):
        """on_bar 默认返回 None。"""

        class ConcreteMethod(BaseMethod):
            def setup(self, ctx):
                self.ctx = ctx

            def generate_signal(self, df):
                return df

        m = ConcreteMethod()
        row = pd.Series({"close": 10.0, "volume": 1000})
        assert m.on_bar(row) is None

    def test_cleanup_noop(self):
        """cleanup 默认不抛异常。"""

        class ConcreteMethod(BaseMethod):
            def setup(self, ctx):
                self.ctx = ctx

            def generate_signal(self, df):
                return df

        m = ConcreteMethod()
        m.cleanup()  # should not raise

    def test_on_state_save_default(self):
        """on_state_save 默认返回空字典。"""

        class ConcreteMethod(BaseMethod):
            def setup(self, ctx):
                self.ctx = ctx

            def generate_signal(self, df):
                return df

        m = ConcreteMethod()
        assert m.on_state_save() == {}

    def test_on_state_restore_noop(self):
        """on_state_restore 默认不抛异常。"""

        class ConcreteMethod(BaseMethod):
            def setup(self, ctx):
                self.ctx = ctx

            def generate_signal(self, df):
                return df

        m = ConcreteMethod()
        m.on_state_restore({"foo": "bar"})  # should not raise

    def test_on_bar_not_async(self):
        """验证 on_bar 不是 async def（防止错误使用）。"""

        class GoodMethod(BaseMethod):
            def setup(self, ctx):
                pass

            def generate_signal(self, df):
                return df

        # 检查方法是否为协程
        assert not hasattr(
            GoodMethod.on_bar, "__code__"
        ) or not hasattr(GoodMethod.on_bar, "__await__")

    def test_setup_accepts_context(self):
        """setup(ctx) 接收 StrategyContext 实例。"""

        class ConcreteMethod(BaseMethod):
            def setup(self, ctx):
                self.ctx = ctx

            def generate_signal(self, df):
                return df

        ctx = StrategyContext(symbol="601857.SH", method_name="test")
        m = ConcreteMethod()
        m.setup(ctx)
        assert m.ctx is ctx
        assert m.ctx.symbol == "601857.SH"

    def test_generate_signal_accepts_dataframe(self):
        """generate_signal(df) 接收 pd.DataFrame 并正确输出。"""

        class ConcreteMethod(BaseMethod):
            def setup(self, ctx):
                pass

            def generate_signal(self, df):
                return df  # 简单透传

        m = ConcreteMethod()
        df = pd.DataFrame({"close": [10.0, 11.0]})
        result = m.generate_signal(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2


# ══════════════════════════════════════════════════════════════════════
# B3 / B4 / B5 / B6: MethodResult
# ══════════════════════════════════════════════════════════════════════


class TestMethodResult:
    """B3-B6: MethodResult 构造、校验、自动计算。"""

    # ── Fixtures ──────────────────────────────────────────────────

    @pytest.fixture
    def valid_signals(self) -> pd.DataFrame:
        """创建一个有效的 signals DataFrame。"""
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        return pd.DataFrame(
            {"signal": [1, 0, -1, 0, 1], "close": [10.0] * 5}, index=dates
        )

    # ── B3: 正常构造 ─────────────────────────────────────────────

    def test_normal_construction(self, valid_signals):
        """有效输入可正常构造。"""
        result = MethodResult(signals=valid_signals, method_name="test")
        assert result.method_name == "test"
        assert isinstance(result, MethodResult)

    def test_normal_construction_all_fields(self, valid_signals):
        """各字段正常传入。"""
        result = MethodResult(
            signals=valid_signals,
            indicators=None,
            method_name="macd",
            params={"fast": 12, "slow": 26},
            statistics={"sharpe": 1.5, "total_return": 0.05},
            completed_time="2025-01-01T00:00:00+08:00",
            duration_ms=123.45,
            errors=[],
            metadata={"source": "test"},
        )
        assert result.method_name == "macd"
        assert result.params == {"fast": 12, "slow": 26}
        assert result.statistics["sharpe"] == 1.5

    # ── B5: 空 DataFrame 防御 ────────────────────────────────────

    def test_empty_signals(self):
        """空 DataFrame 不抛异常，n_bars=0。"""
        empty = pd.DataFrame()
        result = MethodResult(signals=empty)
        assert result.n_bars == 0
        assert result.n_signals == 0
        assert result.signal_ratio == 0.0

    def test_non_dataframe_raises(self):
        """非 DataFrame 输入抛 TypeError。"""
        with pytest.raises(TypeError, match="必须是 pd.DataFrame"):
            MethodResult(signals=[1, 2, 3])  # type: ignore[arg-type]

    # ── B5: signal 列存在性 ──────────────────────────────────────

    def test_missing_signal_column_raises(self):
        """缺少 signal 列抛 ValueError。"""
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        df = pd.DataFrame({"close": [10.0] * 3}, index=dates)
        with pytest.raises(ValueError, match="必须包含 'signal' 列"):
            MethodResult(signals=df)

    # ── B6: 信号值域校验 ─────────────────────────────────────────

    def test_signal_value_range_valid(self, valid_signals):
        """{-1, 0, 1} 内的信号值正常通过。"""
        result = MethodResult(signals=valid_signals)
        assert result.n_signals == 3  # 1, -1, 1 三个非零

    def test_signal_value_range_invalid(self):
        """值为 2 的 signal 应抛 ValueError。"""
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        df = pd.DataFrame({"signal": [1, 0, 2]}, index=dates)
        with pytest.raises(ValueError, match="值域必须"):
            MethodResult(signals=df)

    def test_signal_value_range_negative_outside(self):
        """值为 -2 的 signal 应抛 ValueError。"""
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        df = pd.DataFrame({"signal": [0, -1, -2]}, index=dates)
        with pytest.raises(ValueError, match="值域必须"):
            MethodResult(signals=df)

    # ── B7: 索引类型校验 ─────────────────────────────────────────

    def test_index_datetime_valid(self, valid_signals):
        """DatetimeIndex 通过索引校验。"""
        result = MethodResult(signals=valid_signals)
        assert result.n_bars == 5

    def test_index_non_datetime_raises(self):
        """非 DatetimeIndex 索引抛 ValueError。"""
        df = pd.DataFrame({"signal": [1, 0, -1]}, index=[0, 1, 2])
        with pytest.raises(ValueError, match="DatetimeIndex"):
            MethodResult(signals=df)

    def test_index_range_index_raises(self):
        """RangeIndex（默认整数索引）抛 ValueError。"""
        df = pd.DataFrame({"signal": [1, 0, -1]})
        with pytest.raises(ValueError, match="DatetimeIndex"):
            MethodResult(signals=df)

    # ── B5: 自动计算统计字段 ─────────────────────────────────────

    def test_n_bars_auto(self, valid_signals):
        """n_bars 自动等于 DataFrame 行数。"""
        result = MethodResult(signals=valid_signals)
        assert result.n_bars == 5

    def test_n_signals_auto(self, valid_signals):
        """n_signals 自动计算非零信号数。"""
        result = MethodResult(signals=valid_signals)
        assert result.n_signals == 3

    def test_signal_ratio_auto(self, valid_signals):
        """signal_ratio 自动计算。"""
        result = MethodResult(signals=valid_signals)
        assert result.signal_ratio == 3 / 5

    def test_signal_ratio_no_signals(self):
        """全零信号的 ratio 为 0。"""
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = pd.DataFrame({"signal": [0, 0, 0, 0, 0]}, index=dates)
        result = MethodResult(signals=df)
        assert result.n_signals == 0
        assert result.signal_ratio == 0.0

    # ── B8: Optional 字段默认值 ──────────────────────────────────

    def test_completed_time_default_none(self):
        """completed_time 默认 None（墨萱 P2）。"""
        dates = pd.date_range("2025-01-01", periods=2, freq="D")
        df = pd.DataFrame({"signal": [1, -1]}, index=dates)
        result = MethodResult(signals=df)
        assert result.completed_time is None

    def test_duration_ms_default_none(self):
        """duration_ms 默认 None（墨萱 P2）。"""
        dates = pd.date_range("2025-01-01", periods=2, freq="D")
        df = pd.DataFrame({"signal": [1, -1]}, index=dates)
        result = MethodResult(signals=df)
        assert result.duration_ms is None

    def test_statistics_type_check_warns(self):
        """statistics 含非 float/int 值发出警告（墨萱 P2）。"""
        dates = pd.date_range("2025-01-01", periods=2, freq="D")
        df = pd.DataFrame({"signal": [1, -1]}, index=dates)
        with pytest.warns(UserWarning, match="statistics"):
            MethodResult(
                signals=df,
                statistics={"bad": "string_value"},
            )


# ══════════════════════════════════════════════════════════════════════
# B7 / B14: MethodManifest / FACTOR_META 协议常数
# ══════════════════════════════════════════════════════════════════════


class TestMethodManifest:
    """B7: METHOD_META 协议常量结构验证。"""

    def test_manifest_required_fields_defined(self):
        """MANIFEST_REQUIRED_FIELDS 包含必要项。"""
        assert "name" in MANIFEST_REQUIRED_FIELDS
        assert "version" in MANIFEST_REQUIRED_FIELDS
        assert "capabilities" in MANIFEST_REQUIRED_FIELDS
        assert "default_params" in MANIFEST_REQUIRED_FIELDS

    def test_capabilities_required_fields_defined(self):
        """CAPABILITIES_REQUIRED_FIELDS 包含必要子字段。"""
        assert "long_only" in CAPABILITIES_REQUIRED_FIELDS
        assert "intraday_support" in CAPABILITIES_REQUIRED_FIELDS
        assert "requires_state" in CAPABILITIES_REQUIRED_FIELDS


class TestFACTOR_META:
    """B14: FACTOR_META 协议常量结构验证。"""

    def test_factor_meta_required_fields_defined(self):
        """FACTOR_META_REQUIRED_FIELDS 包含必要项。"""
        assert "name" in FACTOR_META_REQUIRED_FIELDS
        assert "version" in FACTOR_META_REQUIRED_FIELDS
        assert "category" in FACTOR_META_REQUIRED_FIELDS
        assert "default_params" in FACTOR_META_REQUIRED_FIELDS


# ══════════════════════════════════════════════════════════════════════
# B8: validate_manifest()
# ══════════════════════════════════════════════════════════════════════


class TestValidateManifest:
    """B8: validate_manifest 校验工具。"""

    @pytest.fixture
    def valid_manifest(self) -> Dict[str, Any]:
        return {
            "name": "macd",
            "version": "1.0.0",
            "capabilities": {
                "long_only": True,
                "intraday_support": False,
                "requires_state": False,
            },
            "default_params": {"fast": 12, "slow": 26, "signal": 9},
        }

    def test_valid_passes(self, valid_manifest):
        """合规 manifest 返回空列表。"""
        errors = validate_manifest(valid_manifest)
        assert errors == []

    def test_missing_name(self, valid_manifest):
        """缺少 name 报错。"""
        del valid_manifest["name"]
        errors = validate_manifest(valid_manifest)
        assert any("name" in e for e in errors)

    def test_missing_version(self, valid_manifest):
        """缺少 version 报错。"""
        del valid_manifest["version"]
        errors = validate_manifest(valid_manifest)
        assert any("version" in e for e in errors)

    def test_missing_capabilities(self, valid_manifest):
        """缺少 capabilities 报错。"""
        del valid_manifest["capabilities"]
        errors = validate_manifest(valid_manifest)
        assert any("capabilities" in e for e in errors)

    def test_missing_default_params(self, valid_manifest):
        """缺少 default_params 报错。"""
        del valid_manifest["default_params"]
        errors = validate_manifest(valid_manifest)
        assert any("default_params" in e for e in errors)

    def test_missing_capability_long_only(self, valid_manifest):
        """capabilities 缺少 long_only 报错。"""
        del valid_manifest["capabilities"]["long_only"]
        errors = validate_manifest(valid_manifest)
        assert any("long_only" in e for e in errors)

    def test_missing_capability_intraday(self, valid_manifest):
        """capabilities 缺少 intraday_support 报错。"""
        del valid_manifest["capabilities"]["intraday_support"]
        errors = validate_manifest(valid_manifest)
        assert any("intraday_support" in e for e in errors)

    def test_missing_capability_requires_state(self, valid_manifest):
        """capabilities 缺少 requires_state 报错。"""
        del valid_manifest["capabilities"]["requires_state"]
        errors = validate_manifest(valid_manifest)
        assert any("requires_state" in e for e in errors)

    def test_capability_non_bool_raises(self, valid_manifest):
        """capabilities 子字段非 bool 报错。"""
        valid_manifest["capabilities"]["long_only"] = "yes"  # type: ignore[assignment]
        errors = validate_manifest(valid_manifest)
        assert any("long_only" in e and "bool" in e for e in errors)

    def test_empty_manifest_returns_multiple_errors(self):
        """空 manifest 返回多个缺失错误。"""
        errors = validate_manifest({})
        assert len(errors) >= len(MANIFEST_REQUIRED_FIELDS)

    def test_all_errors_together(self):
        """完全空的 manifest 返回全部 7 个错误（4 顶层 + 3 capabilities）。"""
        errors = validate_manifest({})
        assert len(errors) == 7  # 4 顶层 + 3 capabilities


class TestValidateFactorMeta:
    """FACTOR_META 校验工具。"""

    @pytest.fixture
    def valid_meta(self) -> Dict[str, Any]:
        return {
            "name": "momentum",
            "version": "1.0.0",
            "category": "momentum",
            "default_params": {"window": 20},
        }

    def test_valid_passes(self, valid_meta):
        """合规 FACTOR_META 返回空列表。"""
        errors = validate_factor_meta(valid_meta)
        assert errors == []

    def test_missing_category(self, valid_meta):
        """缺少 category 报错。"""
        del valid_meta["category"]
        errors = validate_factor_meta(valid_meta)
        assert any("category" in e for e in errors)

    def test_empty_meta_errors(self):
        """空 meta 返回全部 4 个缺失错误。"""
        errors = validate_factor_meta({})
        assert len(errors) == 4


# ══════════════════════════════════════════════════════════════════════
# B9: StrategyContext frozen 不可变
# ══════════════════════════════════════════════════════════════════════


class TestStrategyContext:
    """B9 + B11 + B12: StrategyContext frozen 属性 + 双层查找 + 懒加载 Logger。"""

    def test_frozen_cannot_modify(self):
        """frozen dataclass 无法直接修改属性。"""
        ctx = StrategyContext(symbol="601857.SH")
        with pytest.raises(AttributeError):
            ctx.symbol = "000001.SZ"  # type: ignore[misc]

    def test_frozen_cannot_modify_nested(self):
        """frozen 不可变同样适用于字典值（通过直接属性赋值）。"""
        ctx = StrategyContext(config={"key": "value"})
        with pytest.raises(AttributeError):
            ctx.config = {"other": "value"}  # type: ignore[misc]

    def test_default_values(self):
        """默认值正确设置。"""
        ctx = StrategyContext()
        assert ctx.symbol == ""
        assert ctx.tick_size == 0.01
        assert ctx.lot_size == 100
        assert ctx.initial_cash == 1_000_000.0
        assert ctx.benchmark == "000300.SH"
        assert ctx.data_frequency == "daily"
        assert ctx.debug_mode is False

    def test_custom_values(self):
        """自定义构造参数生效。"""
        ctx = StrategyContext(
            symbol="601857.SH",
            initial_cash=500_000.0,
            verbose=True,
        )
        assert ctx.symbol == "601857.SH"
        assert ctx.initial_cash == 500_000.0
        assert ctx.verbose is True

    # ── B11: get_config 双层查找 ─────────────────────────────────

    def test_get_config_method_level(self):
        """方法级 config 优先返回。"""
        ctx = StrategyContext(
            config={"param_a": 42},
            global_config={"param_a": 99, "param_b": "global"},
        )
        assert ctx.get_config("param_a") == 42

    def test_get_config_global_fallback(self):
        """方法级 config 不存在时，后备到 global_config。"""
        ctx = StrategyContext(
            config={"param_a": 42},
            global_config={"param_b": "global_val"},
        )
        assert ctx.get_config("param_b") == "global_val"

    def test_get_config_default(self):
        """两层均不存在时返回默认值。"""
        ctx = StrategyContext()
        assert ctx.get_config("nonexistent", "fallback") == "fallback"

    def test_get_config_nonexistent_no_default(self):
        """两层均不存在且无默认值时返回 None。"""
        ctx = StrategyContext()
        assert ctx.get_config("nonexistent") is None

    # ── B12: get_logger 懒加载 ───────────────────────────────────

    def test_get_logger_returns_logger(self):
        """get_logger 返回 Logger 实例。"""
        ctx = StrategyContext(method_name="test_method")
        logger = ctx.get_logger()
        assert isinstance(logger, logging.Logger)

    def test_get_logger_caches(self):
        """同一 ctx 多次 get_logger 返回同一实例。"""
        ctx = StrategyContext(method_name="test_method")
        logger1 = ctx.get_logger()
        logger2 = ctx.get_logger()
        assert logger1 is logger2

    def test_get_logger_name(self):
        """logger 名称基于 method_name。"""
        ctx = StrategyContext(method_name="my_strategy")
        logger = ctx.get_logger()
        assert "my_strategy" in logger.name

    def test_get_logger_default_name(self):
        """method_name 为空时 logger 使用 unknown。"""
        ctx = StrategyContext()
        logger = ctx.get_logger()
        assert "unknown" in logger.name

    def test_get_logger_lazy(self):
        """首次 get_logger 前，runtime.logger 为 None。"""
        ctx = StrategyContext()
        assert ctx.runtime.logger is None

    def test_get_logger_populates_runtime(self):
        """调用 get_logger 后 runtime.logger 不为 None。"""
        ctx = StrategyContext(method_name="lazy_test")
        _ = ctx.get_logger()
        assert ctx.runtime.logger is not None
        assert isinstance(ctx.runtime.logger, logging.Logger)

    def test_runtime_is_mutable(self):
        """runtime 虽是 frozen 中的字段，但 RuntimeState 本身可变。"""
        ctx = StrategyContext()
        # runtime 对象的字段可以直接修改
        ctx.runtime.current_cash = 500_000.0
        ctx.runtime.positions = {"601857.SH": 1000.0}
        assert ctx.runtime.current_cash == 500_000.0
        assert ctx.runtime.positions["601857.SH"] == 1000.0


# ══════════════════════════════════════════════════════════════════════
# B10: RuntimeState mutable
# ══════════════════════════════════════════════════════════════════════


class TestRuntimeState:
    """B10: RuntimeState 可变状态。"""

    def test_defaults_none(self):
        """默认值全部为 None。"""
        state = RuntimeState()
        assert state.current_cash is None
        assert state.positions is None
        assert state.logger is None

    def test_mutable_cash(self):
        """current_cash 可直接修改。"""
        state = RuntimeState()
        state.current_cash = 500_000.0
        assert state.current_cash == 500_000.0

    def test_mutable_positions(self):
        """positions 可直接修改。"""
        state = RuntimeState()
        state.positions = {"601857.SH": 1000.0}
        assert state.positions["601857.SH"] == 1000.0

    def test_mutable_logger(self):
        """logger 可直接修改。"""
        state = RuntimeState()
        logger = logging.getLogger("test")
        state.logger = logger
        assert state.logger is logger

    def test_not_frozen(self):
        """RuntimeState 不是 frozen。"""
        import dataclasses

        assert not dataclasses.fields(RuntimeState)[0].metadata.get("frozen", False)

    def test_field_mutation(self):
        """修改字段后重新赋值成功。"""
        state = RuntimeState(current_cash=100.0)
        assert state.current_cash == 100.0
        state.current_cash = 200.0
        assert state.current_cash == 200.0


# ══════════════════════════════════════════════════════════════════════
# B13: BaseFactor ABC
# ══════════════════════════════════════════════════════════════════════


class TestBaseFactor:
    """B13: BaseFactor 抽象基类强制。"""

    def test_abstract_cannot_instantiate(self):
        """直接实例化 BaseFactor 应抛 TypeError。"""
        with pytest.raises(TypeError):
            BaseFactor()  # type: ignore[abstract]

    def test_subclass_must_implement_compute(self):
        """缺少 compute 的子类实例化时抛 TypeError。"""

        class MissingCompute(BaseFactor):
            pass

        with pytest.raises(TypeError):
            MissingCompute()

    def test_concrete_factor_works(self):
        """完整实现 compute 后可正常实例化。"""

        class MomentumFactor(BaseFactor):
            FACTOR_META = {
                "name": "momentum",
                "version": "1.0.0",
                "category": "momentum",
                "default_params": {"window": 20},
            }

            def compute(self, df):
                return df["close"].pct_change()

        f = MomentumFactor()
        assert isinstance(f, BaseFactor)
        assert f.params["window"] == 20

    def test_compute_returns_series(self):
        """compute 返回 pd.Series。"""

        class MomentumFactor(BaseFactor):
            FACTOR_META = {
                "name": "momentum",
                "version": "1.0.0",
                "category": "momentum",
                "default_params": {"window": 3},
            }

            def compute(self, df):
                return df["close"].pct_change().fillna(0)

        import numpy as np

        f = MomentumFactor()
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        df = pd.DataFrame(
            {"close": [10.0, 11.0, 12.0, 11.5, 10.5]},
            index=dates,
        )
        result = f.compute(df)
        assert isinstance(result, pd.Series)
        assert len(result) == 5

    def test_params_override(self):
        """构造函数 params 覆盖 FACTOR_META.default_params。"""

        class MomentumFactor(BaseFactor):
            FACTOR_META = {
                "name": "momentum",
                "version": "1.0.0",
                "category": "momentum",
                "default_params": {"window": 20},
            }

            def compute(self, df):
                return df["close"].pct_change(self.params["window"])

        f = MomentumFactor(params={"window": 10})
        assert f.params["window"] == 10

    def test_factor_meta_validate(self):
        """使用 validate_factor_meta 校验因子元信息。"""

        class GoodFactor(BaseFactor):
            FACTOR_META = {
                "name": "volatility",
                "version": "1.0.0",
                "category": "volatility",
                "default_params": {"period": 20},
            }

            def compute(self, df):
                return df["close"].pct_change()

        errors = validate_factor_meta(GoodFactor.FACTOR_META)
        assert errors == []


# ══════════════════════════════════════════════════════════════════════
# 模块导入验证
# ══════════════════════════════════════════════════════════════════════


class TestModuleImports:
    """子包可导入，无循环依赖。"""

    def test_import_backtest(self):
        import src.backtest as b

        assert hasattr(b, "__version__")

    def test_import_methods(self):
        from src.backtest.methods import BaseMethod, MethodResult, MethodManifest

        assert BaseMethod is not None
        assert MethodResult is not None
        # MethodManifest 是 type alias，存在即正确
        assert callable(MethodResult)

    def test_import_manifest(self):
        from src.backtest.methods.manifest import (
            validate_manifest,
            validate_factor_meta,
        )

        assert callable(validate_manifest)
        assert callable(validate_factor_meta)

    def test_import_context(self):
        from src.backtest.context import StrategyContext, RuntimeState

        assert StrategyContext is not None
        assert RuntimeState is not None

    def test_import_factors(self):
        from src.backtest.factors import BaseFactor

        assert BaseFactor is not None

    def test_import_engine(self):
        import src.backtest.engine

        assert src.backtest.engine.__doc__ is not None

    def test_import_runners(self):
        import src.backtest.runners

        assert src.backtest.runners.__doc__ is not None

    def test_import_portfolio(self):
        import src.backtest.portfolio

        assert src.backtest.portfolio.__doc__ is not None

    def test_import_reports(self):
        import src.backtest.reports

        assert src.backtest.reports.__doc__ is not None

    def test_import_events(self):
        import src.backtest.events

        assert src.backtest.events.__doc__ is not None

    def test_import_adapters(self):
        import src.backtest.adapters

        assert src.backtest.adapters.__doc__ is not None
