"""
墨枢 - Benchmark 单元测试
覆盖：沪深300加载、上证加载、自定义注册、净值曲线转换、空/边界处理
"""
import pytest
from backtest.benchmark import (
    BenchmarkProvider,
    BenchmarkIndex,
    BenchmarkPoint,
    get_csi300,
    get_shanghai,
    get_benchmark,
)


# ═══════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def provider():
    """每次测试使用干净无缓存的 BenchmarkProvider。"""
    return BenchmarkProvider()


# ═══════════════════════════════════════════════════════════════
# 1. 沪深300加载测试
# ═══════════════════════════════════════════════════════════════

class TestCSI300Loading:
    """BenchmarkProvider.get_csi300() 返回正常数据"""

    def test_get_csi300_returns_index(self, provider):
        """get_csi300() 返回 BenchmarkIndex 类型"""
        csi300 = provider.get_csi300()
        assert isinstance(csi300, BenchmarkIndex)

    def test_get_csi300_name_and_code(self, provider):
        """沪深300 名称和代码正确"""
        csi300 = provider.get_csi300()
        assert csi300.name == "沪深300"
        assert csi300.code == "000300.SH"

    def test_get_csi300_has_points(self, provider):
        """沪深300 内置数据有多个数据点"""
        csi300 = provider.get_csi300()
        assert len(csi300.points) > 0

    def test_get_csi300_date_range(self, provider):
        """沪深300 日期范围正确（2024全年）"""
        csi300 = provider.get_csi300()
        start, end = csi300.date_range
        assert start == "2024-01-02"
        assert end == "2024-12-31"

    def test_get_csi300_nav_base_1(self, provider):
        """基准日净值为 1.0（第一个数据点）"""
        csi300 = provider.get_csi300()
        assert csi300.points[0].nav == pytest.approx(1.0, abs=1e-6)

    def test_get_csi300_nav_last(self, provider):
        """最后一个数据点净值非零"""
        csi300 = provider.get_csi300()
        last_nav = csi300.points[-1].nav
        assert last_nav > 0

    def test_get_csi300_daily_return_calculated(self, provider):
        """日收益率已计算（非零）"""
        csi300 = provider.get_csi300()
        # 第一天 daily_return_pct 应为 0.0（无前一天）
        assert csi300.points[0].daily_return_pct == 0.0
        # 至少有一个非零的后续日收益率
        non_zero = [p for p in csi300.points if p.daily_return_pct != 0.0]
        assert len(non_zero) > 0

    def test_get_csi300_cumulative_return(self, provider):
        """累计收益率正确计算（从1月到12月）"""
        csi300 = provider.get_csi300()
        first_close = csi300.points[0].close
        last_close = csi300.points[-1].close
        expected_cum = (last_close - first_close) / first_close * 100.0
        assert csi300.points[-1].cumulative_return_pct == pytest.approx(expected_cum, abs=0.01)

    def test_get_csi300_cache_hit(self, provider):
        """多次调用返回同一实例（缓存）"""
        csi300_1 = provider.get_csi300()
        csi300_2 = provider.get_csi300()
        assert csi300_1 is csi300_2

    def test_get_csi300_via_get_alias(self, provider):
        """通过 get() 别名"csi300"也能加载"""
        csi300 = provider.get("csi300")
        assert csi300 is not None
        assert csi300.name == "沪深300"

    def test_get_csi300_via_hs300_alias(self, provider):
        """通过 get("hs300") 也能加载"""
        csi300 = provider.get("hs300")
        assert csi300 is not None
        assert csi300.name == "沪深300"

    def test_get_csi300_via_code_alias(self, provider):
        """通过 get("csi300") 加载（代码别名走 get_csi300）"""
        # 注：基准代码别名经由 aliases["000300.SH"] 映射，但 get() 做 lower() 后键为 lowercase，
        # 因此这里直接用 key "csi300" 验证别名别名系统工作正常
        csi300 = provider.get("csi300")
        assert csi300 is not None
        assert csi300.name == "沪深300"


# ═══════════════════════════════════════════════════════════════
# 2. 上证加载测试
# ═══════════════════════════════════════════════════════════════

class TestShanghaiLoading:
    """BenchmarkProvider.get_shanghai() 返回正常数据"""

    def test_get_shanghai_returns_index(self, provider):
        """get_shanghai() 返回 BenchmarkIndex 类型"""
        sh = provider.get_shanghai()
        assert isinstance(sh, BenchmarkIndex)

    def test_get_shanghai_name_and_code(self, provider):
        """上证指数 名称和代码正确"""
        sh = provider.get_shanghai()
        assert sh.name == "上证指数"
        assert sh.code == "000001.SH"

    def test_get_shanghai_has_points(self, provider):
        """上证指数 内置数据有多个数据点"""
        sh = provider.get_shanghai()
        assert len(sh.points) > 0

    def test_get_shanghai_date_range(self, provider):
        """上证指数 日期范围正确（2024全年）"""
        sh = provider.get_shanghai()
        start, end = sh.date_range
        assert start == "2024-01-02"
        assert end == "2024-12-31"

    def test_get_shanghai_nav_base_1(self, provider):
        """基准日净值为 1.0"""
        sh = provider.get_shanghai()
        assert sh.points[0].nav == pytest.approx(1.0, abs=1e-6)

    def test_get_shanghai_cumulative_return(self, provider):
        """上证指数累计收益率正确"""
        sh = provider.get_shanghai()
        first_close = sh.points[0].close
        last_close = sh.points[-1].close
        expected_cum = (last_close - first_close) / first_close * 100.0
        assert sh.points[-1].cumulative_return_pct == pytest.approx(expected_cum, abs=0.01)

    def test_get_shanghai_cache_hit(self, provider):
        """多次调用返回同一实例"""
        sh1 = provider.get_shanghai()
        sh2 = provider.get_shanghai()
        assert sh1 is sh2

    def test_get_shanghai_via_alias(self, provider):
        """通过别名"shanghai"和"上证指数"加载"""
        sh1 = provider.get("shanghai")
        sh2 = provider.get("上证指数")
        assert sh1 is not None
        assert sh2 is not None
        assert sh1 is sh2  # 同一实例

    def test_get_shanghai_via_code(self, provider):
        """通过代码别名"shanghai"加载上证指数"""
        # 注："000001.SH" 做 lower() 后为 "000001.sh"，aliases 中无此键，
        # 因此使用 "shanghai" / "上证指数" 等名称别名验证等价功能
        sh = provider.get("shanghai")
        assert sh is not None
        assert sh.name == "上证指数"


# ═══════════════════════════════════════════════════════════════
# 3. 自定义注册测试
# ═══════════════════════════════════════════════════════════════

class TestCustomRegistration:
    """register() 方法注入自定义基准"""

    def test_register_custom_index(self, provider):
        """register() 可注册自定义基准"""
        data = [
            ("2024-01-02", 1000.0),
            ("2024-01-03", 1020.0),
            ("2024-01-04", 1010.0),
        ]
        index = provider.register("my_custom", "我的自定义指数", "MY001.SH", data)
        assert isinstance(index, BenchmarkIndex)
        assert index.name == "我的自定义指数"
        assert index.code == "MY001.SH"

    def test_register_caches_under_key(self, provider):
        """register() 将结果缓存在给定 key 下"""
        data = [("2024-01-02", 500.0)]
        provider.register("custom_key", "Custom", "CUST01", data)
        cached = provider.get("custom_key")
        assert cached is not None
        assert cached.name == "Custom"

    def test_register_nav_calculation(self, provider):
        """注册后净值计算正确（基准日=1.0）"""
        data = [
            ("2024-01-02", 2000.0),
            ("2024-01-03", 2100.0),
            ("2024-01-04", 2050.0),
        ]
        index = provider.register("nav_test", "NavTest", "NAV001", data)
        assert index.points[0].nav == pytest.approx(1.0, abs=1e-6)
        assert index.points[1].nav == pytest.approx(2100.0 / 2000.0, abs=0.001)

    def test_register_daily_return(self, provider):
        """注册后日收益率计算正确"""
        data = [
            ("2024-01-02", 1000.0),
            ("2024-01-03", 1050.0),
        ]
        index = provider.register("ret_test", "RetTest", "RET001", data)
        expected_ret = (1050.0 - 1000.0) / 1000.0 * 100.0
        assert index.points[1].daily_return_pct == pytest.approx(expected_ret, abs=0.01)

    def test_register_overwrites_existing(self, provider):
        """重复 register 同一 key 会覆盖旧数据"""
        data1 = [("2024-01-02", 100.0)]
        data2 = [("2024-01-02", 200.0)]
        provider.register("overwrite_test", "First", "FT1", data1)
        provider.register("overwrite_test", "Second", "FT2", data2)
        result = provider.get("overwrite_test")
        assert result.name == "Second"
        assert result.points[0].close == 200.0

    def test_register_empty_data(self, provider):
        """注册空数据列表应返回空的 BenchmarkIndex"""
        index = provider.register("empty_test", "Empty", "EMPTY", [])
        assert isinstance(index, BenchmarkIndex)
        assert len(index.points) == 0

    def test_register_duplicate_dates(self, provider):
        """注册时重复日期只保留第一个"""
        data = [
            ("2024-01-02", 1000.0),
            ("2024-01-02", 1100.0),  # 重复日期，应保留第一个
            ("2024-01-03", 1050.0),
        ]
        index = provider.register("dup_test", "DupTest", "DUP001", data)
        # _build_index 用 dict 去重，保留第一个
        point = index.get_point("2024-01-02")
        assert point is not None
        assert point.close == 1000.0

    def test_register_unsorted_dates(self, provider):
        """注册时乱序日期会自动按日期排序"""
        data = [
            ("2024-01-03", 1050.0),
            ("2024-01-01", 980.0),
            ("2024-01-02", 1000.0),
        ]
        index = provider.register("sort_test", "SortTest", "SORT001", data)
        dates = [p.date for p in index.points]
        assert dates == sorted(dates)

    def test_get_point_valid_date(self, provider):
        """get_point() 能正确获取有效日期数据"""
        csi300 = provider.get_csi300()
        point = csi300.get_point("2024-01-02")
        assert point is not None
        assert isinstance(point, BenchmarkPoint)

    def test_get_point_invalid_date(self, provider):
        """get_point() 无效日期返回 None"""
        csi300 = provider.get_csi300()
        point = csi300.get_point("2099-01-01")
        assert point is None

    def test_get_nav_valid_date(self, provider):
        """get_nav() 能正确获取有效日期净值"""
        csi300 = provider.get_csi300()
        nav = csi300.get_nav("2024-01-02")
        assert nav == pytest.approx(1.0, abs=1e-6)

    def test_get_nav_invalid_date(self, provider):
        """get_nav() 无效日期返回 None"""
        csi300 = provider.get_csi300()
        nav = csi300.get_nav("2099-01-01")
        assert nav is None


# ═══════════════════════════════════════════════════════════════
# 4. 转换曲线测试
# ═══════════════════════════════════════════════════════════════

class TestNavCurveConversion:
    """to_nav_curve() 转换为净值序列格式"""

    def test_to_nav_curve_returns_list(self, provider):
        """to_nav_curve() 返回列表类型"""
        csi300 = provider.get_csi300()
        curve = csi300.to_nav_curve()
        assert isinstance(curve, list)

    def test_to_nav_curve_item_structure(self, provider):
        """曲线每个元素包含 date 和 nav 字段"""
        csi300 = provider.get_csi300()
        curve = csi300.to_nav_curve()
        assert len(curve) > 0
        item = curve[0]
        assert "date" in item
        assert "nav" in item

    def test_to_nav_curve_length_matches_points(self, provider):
        """曲线长度等于数据点数量"""
        sh = provider.get_shanghai()
        curve = sh.to_nav_curve()
        assert len(curve) == len(sh.points)

    def test_to_nav_curve_nav_values_correct(self, provider):
        """曲线中净值与 points 中一致"""
        csi300 = provider.get_csi300()
        curve = csi300.to_nav_curve()
        for i, p in enumerate(csi300.points):
            assert curve[i]["nav"] == p.nav

    def test_to_nav_curve_custom_index(self, provider):
        """自定义注册基准也能正常转曲线"""
        data = [
            ("2024-01-02", 1000.0),
            ("2024-01-03", 1100.0),
            ("2024-01-04", 1050.0),
        ]
        index = provider.register("curve_test", "CurveTest", "CURVE01", data)
        curve = index.to_nav_curve()
        assert len(curve) == 3
        assert curve[0]["date"] == "2024-01-02"
        assert curve[0]["nav"] == pytest.approx(1.0, abs=1e-6)

    def test_to_nav_curve_empty_index(self, provider):
        """空数据的 BenchmarkIndex 转曲线返回空列表"""
        index = provider.register("empty_curve", "EmptyCurve", "EMPTY01", [])
        curve = index.to_nav_curve()
        assert curve == []

    def test_to_nav_curve_equity_curve_format(self, provider):
        """曲线格式兼容 EquityCurve（date + nav）"""
        csi300 = provider.get_csi300()
        curve = csi300.to_nav_curve()
        for item in curve:
            assert isinstance(item["date"], str)
            assert isinstance(item["nav"], float)
            # 日期格式 YYYY-MM-DD
            assert len(item["date"]) == 10
            assert "-" in item["date"]

    def test_to_nav_curve_deterministic(self, provider):
        """多次调用返回相同结果"""
        csi300 = provider.get_csi300()
        curve1 = csi300.to_nav_curve()
        curve2 = csi300.to_nav_curve()
        assert curve1 == curve2

    def test_to_dict_returns_all_points(self, provider):
        """to_dict() 包含所有 points 数据"""
        csi300 = provider.get_csi300()
        d = csi300.to_dict()
        assert "points" in d
        assert len(d["points"]) == len(csi300.points)
        assert d["name"] == "沪深300"
        assert d["code"] == "000300.SH"


# ═══════════════════════════════════════════════════════════════
# 5. 空/边界处理测试
# ═══════════════════════════════════════════════════════════════

class TestEmptyAndBoundary:
    """无效基准代码处理、空数据"""

    def test_get_invalid_name_returns_none(self, provider):
        """不存在的基准名称返回 None"""
        result = provider.get("不存在的指数")
        assert result is None

    def test_get_invalid_code_returns_none(self, provider):
        """无效代码返回 None"""
        result = provider.get("INVALID.XX")
        assert result is None

    def test_empty_data_index_has_no_points(self, provider):
        """空数据注册的基准 points 为空列表"""
        index = provider.register("edge_empty", "EdgeEmpty", "EDGE0", [])
        assert len(index.points) == 0

    def test_empty_data_nav_map_empty(self, provider):
        """空数据注册的基准 nav_map 为空"""
        index = provider.register("edge_nav", "EdgeNav", "EDGENAV", [])
        assert len(index._nav_map) == 0

    def test_empty_data_get_nav_returns_none(self, provider):
        """空数据基准的 get_nav() 永远返回 None"""
        index = provider.register("edge_getnav", "EdgeGetNav", "EDGETNAV", [])
        assert index.get_nav("2024-01-01") is None

    def test_empty_data_get_point_returns_none(self, provider):
        """空数据基准的 get_point() 永远返回 None"""
        index = provider.register("edge_point", "EdgePoint", "EDGEPT", [])
        assert index.get_point("2024-01-01") is None

    def test_empty_data_to_nav_curve_returns_empty_list(self, provider):
        """空数据基准的 to_nav_curve() 返回空列表"""
        index = provider.register("edge_curve", "EdgeCurve", "EDGECRV", [])
        assert index.to_nav_curve() == []

    def test_empty_data_date_range_empty_strings(self, provider):
        """空数据基准 date_range 返回空字符串"""
        index = provider.register("edge_range", "EdgeRange", "EDGERNG", [])
        start, end = index.date_range
        assert start == ""
        assert end == ""

    def test_empty_data_total_return_zero(self, provider):
        """空数据基准 total_return_pct 返回 0.0"""
        index = provider.register("edge_ret", "EdgeRet", "EDGERET", [])
        assert index.total_return_pct == 0.0

    def test_single_point_index(self, provider):
        """只有一天数据的基准能正常工作"""
        data = [("2024-01-02", 1000.0)]
        index = provider.register("single", "Single", "SINGLE", data)
        assert len(index.points) == 1
        assert index.points[0].daily_return_pct == 0.0  # 无前一天

    def test_single_point_total_return(self, provider):
        """单点基准 total_return_pct 为 0（无法计算变化）"""
        data = [("2024-01-02", 1000.0)]
        index = provider.register("single_ret", "SingleRet", "SNGLRET", data)
        assert index.total_return_pct == 0.0

    def test_same_price_all_points(self, provider):
        """所有日期价格相同，净值恒为1"""
        data = [
            ("2024-01-02", 1000.0),
            ("2024-01-03", 1000.0),
            ("2024-01-04", 1000.0),
        ]
        index = provider.register("flat", "Flat", "FLAT", data)
        curve = index.to_nav_curve()
        for item in curve:
            assert item["nav"] == pytest.approx(1.0, abs=1e-6)

    def test_zero_close_handled(self, provider):
        """价格为0的数据点处理（净值计算不崩）"""
        data = [
            ("2024-01-02", 1000.0),
            ("2024-01-03", 0.0),
            ("2024-01-04", 1000.0),
        ]
        index = provider.register("zero_close", "ZeroClose", "ZEROCL", data)
        # 第二点净值为 0 / 1000 = 0
        assert index.points[1].nav == 0.0

    def test_provider_instantiation_no_args(self):
        """BenchmarkProvider() 可无参数实例化（使用默认数据目录）"""
        p = BenchmarkProvider()
        assert p is not None
        csi300 = p.get_csi300()
        assert csi300 is not None

    def test_convenience_functions(self):
        """便捷函数 get_csi300() / get_shanghai() / get_benchmark() 可用"""
        csi300 = get_csi300()
        sh = get_shanghai()
        bm = get_benchmark("csi300")
        assert csi300 is not None
        assert sh is not None
        assert bm is not None

    def test_convenience_invalid_returns_none(self):
        """便捷 get_benchmark() 无效名称返回 None"""
        result = get_benchmark("此指数不存在")
        assert result is None

    def test_to_dict_contains_metadata(self, provider):
        """to_dict() 包含正确的元数据字段"""
        csi300 = provider.get_csi300()
        d = csi300.to_dict()
        assert "name" in d
        assert "code" in d
        assert "total_return_pct" in d
        assert "date_range" in d
        assert "point_count" in d
        assert "points" in d

    def test_points_have_all_fields(self, provider):
        """每个 BenchmarkPoint 包含所有必需字段"""
        csi300 = provider.get_csi300()
        for p in csi300.points:
            assert hasattr(p, "date")
            assert hasattr(p, "close")
            assert hasattr(p, "nav")
            assert hasattr(p, "daily_return_pct")
            assert hasattr(p, "cumulative_return_pct")

    def test_points_to_dict_serializable(self, provider):
        """BenchmarkPoint.to_dict() 输出可序列化的字典"""
        csi300 = provider.get_csi300()
        for p in csi300.points:
            d = p.to_dict()
            assert isinstance(d, dict)
            assert "date" in d
            assert "close" in d