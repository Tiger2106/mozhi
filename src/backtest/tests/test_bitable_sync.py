"""
test_bitable_sync — BitableSync 单元测试

Phase 1b 覆盖: 18 个模拟模式测试（1-18）
Phase 1b+ 覆盖: 6 个真实 API 模式测试（19-24）

作者: 墨衡 (Phase 1b) / 墨涵 (Phase 1b+)
创建时间: 2026-05-17
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from backtest.engine.bitable_sync import BitableSync

# ============================================================
# 已弃用：旧版 KnowledgeEntry（v1）
# 仅用于旧测试和回填兼容
# ============================================================


class _LegacyEntry:
    """模拟旧版 KnowledgeEntry 结构（不含 validate）。"""

    def __init__(
        self,
        task_id="bt_001",
        method_name="ma_cross",
        symbol="601857",
        regime="sideways",
        timeframe="4h",
        tags=None,
        source_run_id="run_01",
        completed_time="2026-03-25T12:00:00+08:00",
        insight_summary="移动均线金叉信号，震荡市中有效",
        insight_category="regime_insight",
        confidence=0.85,
        quality_score=85.0,
        total_return=3.2,
        sharpe=1.5,
        max_drawdown=-2.1,
        win_rate=0.65,
        parameters=None,
        statistics=None,
        normalized_params=None,
    ):
        self.task_id = task_id
        self.method_name = method_name
        self.symbol = symbol
        self.regime = regime
        self.timeframe = timeframe
        self.tags = tags or []
        self.source_run_id = source_run_id
        self.completed_time = completed_time
        self.insight_summary = insight_summary
        self.insight_category = insight_category
        self.confidence = confidence
        self.quality_score = quality_score
        self.total_return = total_return
        self.sharpe = sharpe
        self.max_drawdown = max_drawdown
        self.review_status = ""
        self.win_rate = win_rate
        self.parameters = parameters or {"levels": 10}
        self.statistics = statistics or {"avg_hold": 3}
        self.normalized_params = normalized_params or {"n_levels": 10}

    def validate(self):
        pass


# ============================================================
# 工厂函数
# ============================================================


def _make_entry(
    task_id="bt_001",
    method_name="ma_cross",
    symbol="601857",
    regime="sideways",
    timeframe="4h",
    tags=None,
    source_run_id="run_01",
    completed_time="2026-03-25T12:00:00+08:00",
    insight_summary="移动均线金叉信号，震荡市中有效",
    insight_category="regime_insight",
    confidence=0.85,
    quality_score=85.0,
    total_return=3.2,
    sharpe=1.5,
    max_drawdown=-2.1,
    win_rate=0.65,
    parameters=None,
    statistics=None,
    normalized_params=None,
):
    return _LegacyEntry(
        task_id=task_id,
        method_name=method_name,
        symbol=symbol,
        regime=regime,
        timeframe=timeframe,
        tags=tags,
        source_run_id=source_run_id,
        completed_time=completed_time,
        insight_summary=insight_summary,
        insight_category=insight_category,
        confidence=confidence,
        quality_score=quality_score,
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        parameters=parameters,
        statistics=statistics,
        normalized_params=normalized_params,
    )


# ============================================================
# TestBitableSyncSimulate — 模拟模式测试（18 个，不可改动）
# ============================================================


class TestBitableSyncSimulate(unittest.TestCase):
    """BitableSync 模拟模式基础功能。"""

    def setUp(self):
        self.sync = BitableSync()

    # ─── 1. 基础去重 ─────────────────────────────────────────

    def test_dedup_same_key(self):
        """相同 (task_id, method_name, symbol) 不应重复添加。"""
        entry = _make_entry()
        self.assertTrue(self.sync.sync(entry))  # 首次写入
        self.assertEqual(self.sync.synced_count, 1)

        self.assertTrue(self.sync.sync(entry))  # 去重命中
        self.assertEqual(self.sync.synced_count, 1)

    def test_dedup_different_task(self):
        """不同 task_id 应去重+更新。"""
        self.sync.sync(_make_entry(task_id="bt_001"))
        self.sync.sync(_make_entry(task_id="bt_002"))
        self.assertEqual(self.sync.synced_count, 2)

    def test_dedup_different_symbol(self):
        """不同 symbol 不应被误去重。"""
        self.sync.sync(_make_entry(symbol="601857"))
        self.sync.sync(_make_entry(symbol="000001"))
        self.assertEqual(self.sync.synced_count, 2)

    # ─── 2. 模拟模式 ─────────────────────────────────────────

    def test_simulate_default(self):
        """默认启用模拟模式。"""
        self.assertTrue(self.sync._simulate)

    def test_simulate_log(self):
        """模拟模式仅日志，不调用外部 API。"""
        entry = _make_entry()
        with self.assertLogs(level="INFO") as cm:
            self.sync.sync(entry)

        log_text = "\n".join(cm.output)
        self.assertIn("[SIMULATE]", log_text)
        self.assertIn("ma_cross", log_text)
        self.assertIn("601857", log_text)

    # ─── 3. 批量同步 ─────────────────────────────────────────

    def test_sync_batch(self):
        """批量同步应正确处理多条。"""
        entries = [
            _make_entry(task_id="batch_1"),
            _make_entry(task_id="batch_2"),
            _make_entry(task_id="batch_3"),
        ]
        success, fail = self.sync.sync_batch(entries)
        self.assertEqual(success, 3)
        self.assertEqual(fail, 0)
        self.assertEqual(self.sync.synced_count, 3)

    def test_sync_batch_dedup(self):
        """批量中的去重应正常。"""
        entries = [
            _make_entry(task_id="bt_001"),
            _make_entry(task_id="bt_001"),  # 去重
            _make_entry(task_id="bt_001", symbol="000001"),
        ]
        success, fail = self.sync.sync_batch(entries)
        self.assertEqual(success, 3)
        self.assertEqual(self.sync.synced_count, 2)

    # ─── 4. 重试机制 ─────────────────────────────────────────

    def test_retry_queue_empty(self):
        """空重试队列返回 0。"""
        result = self.sync._retry_failed()
        self.assertEqual(result, 0)

    def test_retry_single(self):
        """单个条目的重试。"""
        self.sync._retry_queue.append((_make_entry(task_id="bt_retry"), 0))
        result = self.sync._retry_failed()
        self.assertEqual(result, 1)
        self.assertEqual(self.sync.retry_queue_size, 0)

    def test_retry_all_once(self):
        """多个条目各重试一次。"""
        for i in range(3):
            self.sync._retry_queue.append(
                (_make_entry(task_id=f"bt_r{i}"), 0)
            )
        result = self.sync._retry_failed()
        self.assertEqual(result, 3)
        self.assertEqual(self.sync.retry_queue_size, 0)

    def test_retry_max_exceeded(self):
        """重试次数达上限的条目应被丢弃。"""
        entry = _make_entry(task_id="t_drop", method_name="ma_cross", symbol="601857")
        # 已重试 3 次（等于 max_retries=3）
        self.sync._retry_queue.append((entry, 3))

        result = self.sync._retry_failed()
        self.assertEqual(result, 0)  # 应无成功

        # 队列应被清空（条目被丢弃）
        self.assertEqual(self.sync.retry_queue_size, 0)

    # ─── 5. Schema 版本管理 ──────────────────────────────────

    def test_get_schema_version(self):
        """应返回 SCHEMA_VERSION。"""
        ver = self.sync.get_schema_version()
        self.assertIsInstance(ver, str)
        self.assertTrue(len(ver) > 0)

    def test_upgrade_schema_ok(self):
        """正常升级应返回 True。"""
        old = self.sync.get_schema_version()
        result = self.sync.upgrade_schema("3.0")
        self.assertTrue(result)
        self.assertEqual(self.sync.get_schema_version(), "3.0")
        # 恢复
        self.sync.upgrade_schema(old)

    def test_upgrade_schema_invalid(self):
        """空版本号或相同版本号应抛 ValueError。"""
        with self.assertRaises(ValueError):
            self.sync.upgrade_schema("")

        with self.assertRaises(ValueError):
            self.sync.upgrade_schema(self.sync.get_schema_version())

    # ─── 6. 记录构建 ─────────────────────────────────────────

    def test_build_record(self):
        """_build_record 应返回正确结构。"""
        entry = _make_entry()
        record = self.sync._build_record(entry)
        field_names = set(self.sync.FIELD_MAP.keys())
        for field_name in field_names:
            if field_name in ("signal_ratio", "n_trades"):
                continue
            self.assertIn(field_name, record, f"字段 {field_name} 应存在于记录中")

    def test_build_record_with_optional(self):
        """可选字段应正确映射。"""
        entry = _make_entry(
            regime="trending",
            timeframe="1h",
            tags=["alpha", "test"],
        )
        record = self.sync._build_record(entry)
        self.assertEqual(record["regime"], "trending")
        self.assertEqual(record["timeframe"], "1h")
        self.assertEqual(record["tags"], ["alpha", "test"])

    def test_build_record_all_fields(self):
        """_build_record 应包含所有字段的值。"""
        entry = _make_entry()
        record = self.sync._build_record(entry)

        # 验证必要字段
        self.assertEqual(record["task_id"], "bt_001")
        self.assertEqual(record["method_name"], "ma_cross")
        self.assertEqual(record["symbol"], "601857")
        self.assertEqual(record["source_run_id"], "run_01")
        # completed_time 转为毫秒时间戳，仅验证类型和范围
        self.assertIsInstance(record["completed_time"], int)
        self.assertGreater(record["completed_time"], 1700000000000)
        self.assertEqual(
            record["insight_summary"], "移动均线金叉信号，震荡市中有效"
        )
        self.assertEqual(record["category"], "regime_insight")
        self.assertEqual(record["schema_version"], "2.0")

        # 验证数字字段
        self.assertEqual(record["confidence"], 0.85)
        self.assertEqual(record["quality_score"], 85.0)
        self.assertEqual(record["total_return"], 3.2)
        self.assertEqual(record["sharpe_ratio"], 1.5)
        self.assertEqual(record["max_drawdown"], -2.1)
        self.assertEqual(record["win_rate"], 0.65)

        # 验证选择性字段
        self.assertEqual(record["regime"], "sideways")
        self.assertEqual(record["timeframe"], "4h")
        self.assertEqual(record["category"], "regime_insight")

        import json

        params = json.loads(record["params"])
        self.assertEqual(params["levels"], 10)

    # ─── 7. 同步日志 ─────────────────────────────────────────

    def test_sync_log(self):
        """同步应有 INFO 级别日志记录。"""
        entry = _make_entry()
        with self.assertLogs(level="INFO") as cm:
            self.sync.sync(entry)
        self.assertTrue(any("同步成功" in msg for msg in cm.output))

    def test_sync_with_normalized(self):
        """含 normalized_params 的记录应正确序列化。"""
        entry = _make_entry(normalized_params={"param_key": "param_value"})
        record = self.sync._build_record(entry)
        import json

        params = json.loads(record["source"])
        self.assertEqual(params["param_key"], "param_value")

    # ─── 8. 边界条件 ─────────────────────────────────────────

    def test_sync_empty_task_id(self):
        """空的 task_id 不应崩溃。"""
        entry = _make_entry(task_id="")
        record = self.sync._build_record(entry)
        self.assertEqual(record["task_id"], "")

    def test_sync_empty_method_name(self):
        """空的 method_name 不应崩溃。"""
        entry = _make_entry(method_name="")
        record = self.sync._build_record(entry)
        self.assertEqual(record["method_name"], "")

    def test_sync_empty_entry(self):
        """最少字段的条目应正常同步。"""
        entry = _make_entry(
            regime="",
            timeframe="",
            tags=[],
            insight_summary="",
            insight_category="",
            confidence=None,
            quality_score=None,
            total_return=None,
            sharpe=None,
            max_drawdown=None,
            win_rate=None,
            parameters=None,
            statistics=None,
            normalized_params=None,
        )
        record = self.sync._build_record(entry)
        self.assertIn("task_id", record)
        self.assertIn("method_name", record)


# ════════════════════════════════════════════════════════════
# TestBitableSyncRealMode — 真实 API 模式测试
# ════════════════════════════════════════════════════════════


class TestBitableSyncRealMode(unittest.TestCase):
    """真实飞书 API 模式单元测试（mock urllib.request.urlopen）。"""

    def setUp(self):
        self.sync = BitableSync(
            app_token="test_app_token",
            table_id="test_table_id",
        )
        self.sync.configure_real_mode(
            app_id="cli_test_id",
            app_secret="test_secret",
            simulate=False,
        )

    # ─── 19. 真实模式创建记录 ────────────────────────────────

    @patch("backtest.engine.bitable_sync.time.time", return_value=1000000.0)
    @patch("urllib.request.urlopen")
    def test_real_create_record(self, mock_urlopen, mock_time):
        """真实模式下应调用飞书 API 创建记录。"""
        # Mock 认证 token 响应
        mock_token_resp = MagicMock()
        mock_token_resp.__enter__.return_value = mock_token_resp
        mock_token_resp.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "tenant_access_token": "test_token_abc",
            "expire": 7200,
        }).encode("utf-8")

        # Mock 创建记录响应
        mock_create_resp = MagicMock()
        mock_create_resp.__enter__.return_value = mock_create_resp
        mock_create_resp.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "data": {"record": {"record_id": "rec_test_12345"}},
        }).encode("utf-8")

        mock_urlopen.side_effect = [mock_token_resp, mock_create_resp]

        entry = _make_entry(task_id="real_001", method_name="ma_cross", symbol="601857")
        result = self.sync.sync(entry)

        self.assertTrue(result)
        self.assertEqual(self.sync.synced_count, 1)

        # 验证 API 调用次数
        self.assertEqual(mock_urlopen.call_count, 2)

        # 第一个调用：获取 token
        req1 = mock_urlopen.call_args_list[0][0][0]
        url1 = req1.get_full_url()
        self.assertIn("tenant_access_token/internal", url1)

        # 第二个调用：创建记录
        req2 = mock_urlopen.call_args_list[1][0][0]
        url2 = req2.get_full_url()
        self.assertIn("/records", url2)
        body = json.loads(req2.data.decode("utf-8"))
        self.assertIn("fields", body)
        self.assertEqual(body["fields"]["task_id"], "real_001")

    # ─── 20. 真实模式更新记录 ────────────────────────────────

    @patch("backtest.engine.bitable_sync.time.time", return_value=1000000.0)
    @patch("urllib.request.urlopen")
    def test_real_update_record(self, mock_urlopen, mock_time):
        """已存在的记录应通过 PUT 更新。"""
        # Mock token 响应
        mock_token_resp = MagicMock()
        mock_token_resp.__enter__.return_value = mock_token_resp
        mock_token_resp.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "tenant_access_token": "test_token_abc",
            "expire": 7200,
        }).encode("utf-8")

        # Mock 创建记录响应
        mock_create_resp = MagicMock()
        mock_create_resp.__enter__.return_value = mock_create_resp
        mock_create_resp.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "data": {"record": {"record_id": "rec_test_67890"}},
        }).encode("utf-8")

        # Mock 更新记录响应
        mock_update_resp = MagicMock()
        mock_update_resp.__enter__.return_value = mock_update_resp
        mock_update_resp.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "data": {"record": {"record_id": "rec_test_67890"}},
        }).encode("utf-8")

        mock_urlopen.side_effect = [
            mock_token_resp,   # 1: token for create
            mock_create_resp,  # 2: create
            mock_token_resp,   # 3: token for update
            mock_update_resp,  # 4: update
        ]

        entry = _make_entry(task_id="upd_001", method_name="ma_cross", symbol="601857")

        # 第一次：创建
        r1 = self.sync.sync(entry)
        self.assertTrue(r1)

        # 手动设置去重缓存（模拟已记录的状态）
        key = ("upd_001", "ma_cross", "601857")
        self.sync._synced_keys.add(key)
        self.sync._record_map[key] = "rec_test_67890"

        # 第二次：更新（merge）
        r2 = self.sync.sync(entry)
        self.assertTrue(r2)

        # 验证 PUT 请求被发出（第 3 个调用，token 缓存未过期）
        self.assertGreaterEqual(len(mock_urlopen.call_args_list), 3)
        put_req = mock_urlopen.call_args_list[2][0][0]
        put_url = put_req.get_full_url()
        self.assertIn("records/rec_test_67890", put_url)
        self.assertEqual(put_req.method, "PUT")

    # ─── 21. Token 过期自动刷新 ──────────────────────────────

    @patch("backtest.engine.bitable_sync.time.time", return_value=1000000.0)
    @patch("urllib.request.urlopen")
    def test_token_expiry(self, mock_urlopen, mock_time):
        """Token 过期后应自动刷新。"""
        # 第一个 token 响应（短有效期）
        resp1 = MagicMock()
        resp1.__enter__.return_value = resp1
        resp1.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "tenant_access_token": "token_v1",
            "expire": 10,
        }).encode("utf-8")

        # 第二个 token 响应（刷新后）
        resp2 = MagicMock()
        resp2.__enter__.return_value = resp2
        resp2.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "tenant_access_token": "token_v2",
            "expire": 7200,
        }).encode("utf-8")

        # 创建记录响应
        create_resp = MagicMock()
        create_resp.__enter__.return_value = create_resp
        create_resp.read.return_value = json.dumps({
            "code": 0, "msg": "success",
            "data": {"record": {"record_id": "rec_test_111"}},
        }).encode("utf-8")

        # 第一次同步：token + create
        mock_urlopen.side_effect = [resp1, create_resp]

        entry1 = _make_entry(task_id="tk_001", method_name="ma_cross", symbol="601857")
        self.sync.sync(entry1)

        # 强制 token 过期
        self.sync._token_expires_at = 0.0

        # 第二次同步：应刷新 token（resp2 + create）
        mock_urlopen.side_effect = [resp2, create_resp]

        entry2 = _make_entry(task_id="tk_002", method_name="grid", symbol="000001")
        result = self.sync.sync(entry2)
        self.assertTrue(result)

        # 验证 token 已刷新为 v2
        self.assertEqual(self.sync._token, "token_v2")

        # 验证获取 token 的调用有 2 次
        token_calls = [
            call for call in mock_urlopen.call_args_list
            if "tenant_access_token/internal" in call[0][0].get_full_url()
        ]
        self.assertEqual(len(token_calls), 2)

    # ─── 22. 无凭证安全降级 ──────────────────────────────────

    def test_fallback_to_simulate(self):
        """无凭证时应安全降级到模拟模式。"""
        sync = BitableSync(
            app_token="test_app_token",
            table_id="test_table_id",
        )
        # 强制回退到模拟模式（绕过凭证自动加载）
        sync.configure_real_mode(app_id="", app_secret="", simulate=True)
        self.assertTrue(sync._simulate)

        entry = _make_entry(task_id="fallback_001", method_name="ma_cross", symbol="601857")
        result = sync.sync(entry)
        self.assertTrue(result)
        self.assertEqual(sync.synced_count, 1)

        # 验证模拟标记
        record_id = sync._record_map.get(("fallback_001", "ma_cross", "601857"), "")
        self.assertTrue(record_id.startswith("rec_sim_"))

    # ─── 23. 桥接模式 ────────────────────────────────────────

    def test_bridge_mode(self):
        """桥接模式下应写入 JSON 队列文件。"""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            sync = BitableSync(
                app_token="bridge_app",
                table_id="bridge_table",
            )
            sync.configure_real_mode(
                app_id="",
                app_secret="",
                simulate=False,
                bridge_mode=True,
                bridge_dir=tmpdir,
            )

            self.assertFalse(sync._simulate)
            self.assertTrue(sync.bridge_mode)

            entry = _make_entry(
                task_id="bridge_001",
                method_name="ma_cross",
                symbol="601857",
                insight_summary="桥接模式测试",
            )
            result = sync.sync(entry)
            self.assertTrue(result)

            # 验证队列文件被创建
            files = os.listdir(tmpdir)
            self.assertEqual(len(files), 1)

            with open(os.path.join(tmpdir, files[0]), "r", encoding="utf-8") as f:
                queue_entry = json.load(f)

            self.assertEqual(queue_entry["action"], "create")
            self.assertEqual(queue_entry["app_token"], "bridge_app")
            self.assertEqual(queue_entry["table_id"], "bridge_table")
            self.assertEqual(queue_entry["dedup_key"], "bridge_001_ma_cross_601857")
            self.assertEqual(
                queue_entry["fields"]["insight_summary"], "桥接模式测试"
            )

    # ─── 24. 真实模式批量同步 ────────────────────────────────

    @patch("backtest.engine.bitable_sync.time.time", return_value=1000000.0)
    @patch("urllib.request.urlopen")
    def test_real_sync_batch(self, mock_urlopen, mock_time):
        """真实模式下批量同步应正确调用 API。"""
        # token 响应模板
        def _make_token_resp(token="batch_token"):
            r = MagicMock()
            r.__enter__.return_value = r
            r.read.return_value = json.dumps({
                "code": 0, "msg": "success",
                "tenant_access_token": token, "expire": 7200,
            }).encode("utf-8")
            return r

        # 创建记录响应模板
        def _make_create_resp(rec_id):
            r = MagicMock()
            r.__enter__.return_value = r
            r.read.return_value = json.dumps({
                "code": 0, "msg": "success",
                "data": {"record": {"record_id": rec_id}},
            }).encode("utf-8")
            return r

        # 单个 token + 5 次创建（token 会缓存）
        responses = [_make_token_resp("token_0")]
        for i in range(5):
            responses.append(_make_create_resp(f"rec_batch_{i:03d}"))

        mock_urlopen.side_effect = responses

        # 重置 token 缓存
        self.sync._token = ""
        self.sync._token_expires_at = 0.0

        entries = [
            _make_entry(task_id=f"batch_{i}", method_name="ma_cross", symbol="601857")
            for i in range(5)
        ]
        success, fail = self.sync.sync_batch(entries)

        self.assertEqual(success, 5)
        self.assertEqual(fail, 0)
        self.assertEqual(self.sync.synced_count, 5)


# ════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    unittest.main()
