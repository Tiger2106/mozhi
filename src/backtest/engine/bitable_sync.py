"""
mozhi_platform.src.backtest.engine.bitable_sync — Bitable 同步器

Phase 1b 核心产出 + 真实飞书 API 模式升级。

功能：
  1. 去重 — (task_id, method_name, symbol) 复合键
  2. 更新策略 — merge（同键覆盖 + 异键保留）
  3. 重试 — 指数退避（1s → 2s → 4s → 失败重试队列）
  4. schema_version 演进追踪
  5. 回填支持
  6. 真实飞书 API 模式（_simulate=False）

设计要点：
  - 模拟模式（_simulate=True）：仅日志记录，不发送真实 HTTP 请求
  - 真实模式（_simulate=False）：调用飞书 OpenAPI 创建/更新记录
  - 凭证通过 configure_real_mode() 传入，支持 app_id/app_secret 或桥接模式
  - 去重使用本地 set[tuple] 跟踪（非持久化，重启清空）
  - 重试队列带指数退避

作者: 墨衡 (initial) / 墨涵 (real API upgrade)
创建时间: 2026-05-17
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from backtest.engine.knowledge_entry import KnowledgeEntry

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)


# ─── BitableSync ────────────────────────────────────────────


class BitableSync:
    """飞书 Bitable 同步器。

    将 KnowledgeEntry v2 同步到飞书 Bitable，支持去重、重试、
    schema 版本管理和批量操作。

    **模拟模式**（默认）：_simulate=True 时不发送真实 HTTP
    请求，所有本地逻辑（去重/重试/schema 管理）100% 可用。

    **真实模式**：_simulate=False 时通过飞书 OpenAPI 创建/
    更新 Bitable 记录。

    **桥接模式**：bridge_mode=True 时，将记录写入 JSON 队列
    文件，由主 agent 定期读取并写入。

    Examples:
        >>> sync = BitableSync()
        >>> entry = KnowledgeEntry(
        ...     task_id="bt_001", method_name="ma_cross", symbol="601857",
        ...     completed_time="2026-05-17T12:00:00+08:00",
        ... )
        >>> sync.sync(entry)
        True
    """

    # ─── schema 版本 ─────────────────────────────────────────
    SCHEMA_VERSION = "2.0"

    # ─── Bitable 字段映射 ───────────────────────────────────
    FIELD_MAP: dict[str, tuple[int, str]] = {
        "method_name": (0, "text"),
        "symbol": (1, "text"),
        "regime": (2, "single_select"),
        "timeframe": (3, "single_select"),
        "tags": (4, "multi_select"),
        "source_run_id": (5, "text"),
        "completed_time": (6, "datetime"),
        "insight_summary": (7, "text"),
        "category": (8, "single_select"),
        "confidence": (9, "number"),
        "quality_score": (10, "number"),
        "total_return": (11, "number"),
        "sharpe_ratio": (12, "number"),
        "max_drawdown": (13, "number"),
        "win_rate": (14, "number"),
        "params": (15, "text"),
        "extra": (16, "text"),
        "source": (17, "text"),
        "task_id": (18, "text"),
        "schema_version": (19, "text"),
        "signal_ratio": (20, "number"),
        "n_trades": (21, "number"),
    }

    # ─── 桥接模式默认写入目录 ──────────────────────────────
    DEFAULT_BRIDGE_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "incoming",
        "bitable_queue",
    )

    # ─── 飞书 OpenAPI 基础 URL ─────────────────────────────
    FEISHU_OPENAPI_BASE = "https://open.feishu.cn"

    def __init__(
        self,
        app_token: str = "",
        table_id: str = "",
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ):
        """初始化 Bitable 同步器。

        Args:
            app_token: Bitable app_token（模拟模式下可留空）。
            table_id: 表 ID（模拟模式下可留空）。
            max_retries: API 调用最大重试次数（默认 3）。
            backoff_base: 指数退避基数秒数（默认 1.0）。
        """
        self.app_token = app_token
        self.table_id = table_id
        self.max_retries = max_retries
        self.backoff_base = backoff_base

        # 模拟模式：不调用飞书 API
        self._simulate = True

        # 真实模式凭证
        self._app_id: str = ""
        self._app_secret: str = ""
        self.bridge_mode: bool = False
        self._bridge_dir: str = ""

        # token 缓存（真实模式使用）
        self._token: str = ""
        self._token_expires_at: float = 0.0

        # 自动加载凭证文件
        self._load_credentials()

        # 失败重试队列：[(KnowledgeEntry, 已重试次数)]
        self._retry_queue: list[tuple[KnowledgeEntry, int]] = []

        # 已同步记录去重缓存：(task_id, method_name, symbol)
        self._synced_keys: set[tuple[str, str, str]] = set()

        # 已同步记录的 record_id 映射（key → record_id）
        self._record_map: dict[tuple[str, str, str], str] = {}

    # ─── 配置真实模式 ──────────────────────────────────────

    def configure_real_mode(
        self,
        app_id: str,
        app_secret: str,
        *,
        simulate: bool = False,
        bridge_mode: bool = False,
        bridge_dir: str = "",
    ) -> None:
        """配置切换到真实飞书 API 模式。

        Args:
            app_id: 飞书应用 App ID。
            app_secret: 飞书应用 App Secret。
            simulate: False=真实模式, True=模拟模式（用于降级）。
            bridge_mode: 无直接凭证时使用 JSON 队列文件中转。
            bridge_dir: 队列文件写入目录。
        """
        self._simulate = simulate
        self._app_id = app_id
        self._app_secret = app_secret
        self.bridge_mode = bridge_mode
        self._bridge_dir = bridge_dir or self.DEFAULT_BRIDGE_DIR

        logger.info(
            "BitableSync 已配置: simulate=%s bridge=%s app_token=%s table_id=%s",
            self._simulate,
            self.bridge_mode,
            self.app_token,
            self.table_id,
        )

        # 验证凭证
        if not simulate:
            if not app_id or not app_secret:
                if bridge_mode:
                    logger.info("无直接凭证，使用桥接模式")
                else:
                    logger.warning("缺少 app_id/app_secret，自动启用桥接模式")
                    self.bridge_mode = True
            if (not self.app_token or not self.table_id) and not bridge_mode:
                logger.warning("app_token 或 table_id 为空，将回退到模拟模式")
                self._simulate = True

    # ════════════════════════════════════════════════════════
    # 核心同步方法
    # ════════════════════════════════════════════════════════

    def sync(self, entry: KnowledgeEntry) -> bool:
        """同步一条知识条目到 Bitable。

        Args:
            entry: 知识条目。

        Returns:
            bool: 同步成功返回 True，失败返回 False。
        """
        # 1. 校验
        entry.validate()

        # 2. 计算复合键
        key = self._get_compound_key(entry)

        # 3. 去重检查
        if key in self._synced_keys:
            logger.info(
                "去重命中，执行 merge 更新: task_id=%s method=%s symbol=%s",
                entry.task_id,
                entry.method_name,
                entry.symbol,
            )
            return self._do_update(entry, key)

        # 4. 构建记录
        record = self._build_record(entry)

        # 5. 执行同步
        if self._simulate:
            logger.info(
                "[SIMULATE] 创建记录: task_id=%s method=%s symbol=%s",
                entry.task_id,
                entry.method_name,
                entry.symbol,
            )
            self._synced_keys.add(key)
            record_id = (
                f"rec_sim_{entry.task_id}_{entry.method_name}_{entry.symbol}"
            )
            self._record_map[key] = record_id
        else:
            try:
                record_id = self._create_record(record)
                if record_id:
                    self._synced_keys.add(key)
                    self._record_map[key] = record_id
                else:
                    logger.error("同步失败: 创建记录返回空 record_id")
                    return False
            except Exception as e:
                logger.error(
                    "同步失败(真实API): task_id=%s method=%s symbol=%s error=%s",
                    entry.task_id,
                    entry.method_name,
                    entry.symbol,
                    e,
                )
                return False

        logger.info(
            "同步成功: task_id=%s method=%s symbol=%s record_id=%s",
            entry.task_id,
            entry.method_name,
            entry.symbol,
            record_id,
        )
        return True

    def sync_batch(self, entries: list[KnowledgeEntry]) -> tuple[int, int]:
        """批量同步，返回（成功数, 失败数）。

        Args:
            entries: 知识条目列表。

        Returns:
            tuple[int, int]: (成功数, 失败数)。
        """
        success_count = 0
        fail_count = 0

        for entry in entries:
            try:
                if self.sync(entry):
                    success_count += 1
                else:
                    fail_count += 1
                    self._retry_queue.append((entry, 0))
            except Exception as e:
                logger.error(
                    "同步失败: task_id=%s method=%s symbol=%s error=%s",
                    entry.task_id,
                    entry.method_name,
                    entry.symbol,
                    e,
                )
                fail_count += 1
                self._retry_queue.append((entry, 0))

        return success_count, fail_count

    # ════════════════════════════════════════════════════════
    # 记录构建
    # ════════════════════════════════════════════════════════

    def _build_record(self, entry: KnowledgeEntry) -> dict[str, Any]:
        """将 KnowledgeEntry 转为 Bitable 记录格式。

        Returns: 平坦字段字典（{field_name: value}）。
        """
        record: dict[str, Any] = {}

        # 文本字段
        record["task_id"] = entry.task_id
        record["method_name"] = entry.method_name
        record["symbol"] = entry.symbol
        record["source_run_id"] = entry.source_run_id
        # 转为毫秒时间戳（Bitable 日期字段要求）
        try:
            if entry.completed_time and "T" in entry.completed_time:
                from datetime import datetime
                # 处理 +08:00 时区后缀
                ts_str = entry.completed_time
                if "+" in ts_str:
                    ts_str = ts_str.split("+")[0]
                dt = datetime.fromisoformat(ts_str)
                record["completed_time"] = int(dt.timestamp() * 1000)
            else:
                record["completed_time"] = entry.completed_time
        except Exception:
            record["completed_time"] = entry.completed_time
        record["insight_summary"] = entry.insight_summary
        record["category"] = entry.insight_category
        record["schema_version"] = self.SCHEMA_VERSION

        # 选择性字段
        if entry.regime:
            record["regime"] = entry.regime
        if entry.timeframe:
            record["timeframe"] = entry.timeframe
        record["tags"] = entry.tags or []

        # 数字字段（过滤 None）
        if entry.confidence is not None:
            record["confidence"] = entry.confidence
        if entry.quality_score is not None:
            record["quality_score"] = entry.quality_score
        if entry.total_return is not None:
            record["total_return"] = entry.total_return
        if entry.sharpe is not None:
            record["sharpe_ratio"] = entry.sharpe
        if entry.max_drawdown is not None:
            record["max_drawdown"] = entry.max_drawdown
        if entry.win_rate is not None:
            record["win_rate"] = entry.win_rate

        # JSON 字段序列化
        record["params"] = self._json_dumps(entry.parameters)
        record["extra"] = self._json_dumps(entry.statistics)
        if entry.normalized_params:
            record["source"] = self._json_dumps(entry.normalized_params)

        return record

    # ════════════════════════════════════════════════════════
    # 去重
    # ════════════════════════════════════════════════════════

    def _get_compound_key(self, entry: KnowledgeEntry) -> tuple[str, str, str]:
        """去重复合键: (task_id, method_name, symbol)。"""
        return (entry.task_id, entry.method_name, entry.symbol)

    # ════════════════════════════════════════════════════════
    # 更新策略
    # ════════════════════════════════════════════════════════

    # ════════════════════════════════════════════════════════
    # 凭证加载
    # ════════════════════════════════════════════════════════

    def _load_credentials(self) -> None:
        """从 config/credentials.json 自动加载飞书凭证。

        文件格式：
        {
            "feishu_app_id": "cli_xxx",
            "feishu_app_secret": "xxx"
        }

        仅在 app_id/app_secret 尚未设置时加载，不会覆盖已有值。
        """
        if self._app_id and self._app_secret:
            return  # 已通过构造函数传入，跳过

        import os
        import json

        cred_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "config", "credentials.json"
        )
        cred_path = os.path.normpath(cred_path)

        if not os.path.exists(cred_path):
            logger.debug("凭证文件不存在: %s", cred_path)
            return

        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                creds = json.load(f)

            loaded_id = creds.get("feishu_app_id", "")
            loaded_secret = creds.get("feishu_app_secret", "")

            if loaded_id and loaded_secret:
                self._app_id = loaded_id
                self._app_secret = loaded_secret
                logger.info(
                    "已从 credentials.json 加载飞书凭证: app_id=%s",
                    loaded_id,
                )

                # 如果未配置真实模式，自动切换到非模拟
                if self._simulate and self.app_token:
                    self._simulate = False
                    logger.info("检测到凭证文件，自动切换为真实模式")
            else:
                logger.warning("凭证文件内容不完整: 缺少 app_id 或 app_secret")

        except Exception as e:
            logger.warning("加载凭证文件失败: %s", e)

    # ════════════════════════════════════════════════════════
    # 更新策略
    # ════════════════════════════════════════════════════════

    def _do_update(self, entry: KnowledgeEntry, key: tuple[str, str, str]) -> bool:
        """对已存在的记录执行 merge 更新。

        模拟模式下仅记录日志。
        """
        record_id = self._record_map.get(key, "")
        record = self._build_record(entry)

        if self._simulate:
            logger.info(
                "[SIMULATE] 更新记录: record_id=%s task_id=%s method=%s symbol=%s",
                record_id,
                entry.task_id,
                entry.method_name,
                entry.symbol,
            )
            return True

        try:
            self._update_record(record_id, record)
            logger.info(
                "更新成功: record_id=%s task_id=%s method=%s symbol=%s",
                record_id,
                entry.task_id,
                entry.method_name,
                entry.symbol,
            )
            return True
        except Exception as e:
            logger.error("更新失败(真实API): record_id=%s error=%s", record_id, e)
            return False

    # ════════════════════════════════════════════════════════
    # 重试
    # ════════════════════════════════════════════════════════

    def _retry_failed(self) -> int:
        """重试失败队列中的条目。

        使用指数退避：第 n 次重试等待 backoff_base * (2^(n-1)) 秒。
        模拟模式下 sleep 会被跳过。

        Returns:
            int: 重试成功数。
        """
        if not self._retry_queue:
            logger.info("重试队列为空，无需重试")
            return 0

        new_queue: list[tuple[KnowledgeEntry, int]] = []
        success_count = 0

        for entry, retry_count in self._retry_queue:
            if retry_count >= self.max_retries:
                logger.warning(
                    "重试已达上限(%d次)，放弃: task_id=%s method=%s symbol=%s",
                    self.max_retries,
                    entry.task_id,
                    entry.method_name,
                    entry.symbol,
                )
                continue

            # 指数退避
            wait_seconds = self.backoff_base * (2**retry_count)

            if self._simulate:
                logger.info(
                    "[SIMULATE] 重试(%d/%d) task_id=%s 等待[已跳过]",
                    retry_count + 1,
                    self.max_retries,
                    entry.task_id,
                )
            else:
                logger.info(
                    "重试(%d/%d) task_id=%s 等待%.1fs",
                    retry_count + 1,
                    self.max_retries,
                    entry.task_id,
                    wait_seconds,
                )
                time.sleep(wait_seconds)

            try:
                if self.sync(entry):
                    success_count += 1
                else:
                    new_queue.append((entry, retry_count + 1))
            except Exception:
                new_queue.append((entry, retry_count + 1))

        self._retry_queue = new_queue
        return success_count

    # ════════════════════════════════════════════════════════
    # 飞书 OpenAPI 调用（真实模式）
    # ════════════════════════════════════════════════════════

    def _get_tenant_token(self) -> str:
        """获取飞书 tenant_access_token。

        使用 app_id/app_secret 调用认证 API。
        结果缓存在实例中，expire 前 60 秒自动刷新。

        Returns:
            str: tenant_access_token 或空字符串（失败时）。

        Raises:
            RuntimeError: 凭证缺失时抛出（可被桥接模式绕过）。
        """
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        if not self._app_id or not self._app_secret:
            if self.bridge_mode:
                return "bridge_placeholder"
            raise RuntimeError(
                "飞书凭证缺失: 请设置 app_id/app_secret 或启用 bridge_mode"
            )

        url = f"{self.FEISHU_OPENAPI_BASE}/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self._app_id, "app_secret": self._app_secret}

        import urllib.request
        import urllib.error

        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json; charset=utf-8")

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"获取 tenant_access_token 失败: {e}") from e

        if data.get("code") != 0:
            raise RuntimeError(
                f"飞书认证失败: code={data.get('code')} msg={data.get('msg', '')}"
            )

        self._token = data["tenant_access_token"]
        self._token_expires_at = now + data.get("expire", 7200)
        logger.info(
            "tenant_access_token 获取成功，有效期 %ds",
            data.get("expire", 7200),
        )
        return self._token

    def _create_record(self, fields: dict[str, Any]) -> str:
        """在飞书 Bitable 中创建一条记录。

        Args:
            fields: 平坦字段字典。

        Returns:
            str: record_id（成功）或空字符串（失败）。

        Raises:
            RuntimeError: 配置问题或重试耗尽。
        """
        if not self.app_token or not self.table_id:
            if self.bridge_mode:
                return self._bridge_create_record(fields)
            raise RuntimeError("app_token 和 table_id 不能为空")

        token = self._get_tenant_token()
        if self.bridge_mode and token == "bridge_placeholder":
            return self._bridge_create_record(fields)
        if not token:
            return ""

        url = (
            f"{self.FEISHU_OPENAPI_BASE}/open-apis/bitable/v1/apps"
            f"/{self.app_token}/tables/{self.table_id}/records"
        )
        payload = {"fields": fields}

        import urllib.request
        import urllib.error

        for attempt in range(self.max_retries):
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json; charset=utf-8")

            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                logger.warning(
                    "创建记录失败(attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_base * (2**attempt))
                continue

            if data.get("code") == 0:
                record_id = data["data"]["record"]["record_id"]
                logger.info("创建记录成功: record_id=%s", record_id)
                return record_id

            # token 过期时刷新
            if data.get("code") == 99991663:
                logger.info("token 已过期，正在刷新...")
                self._token = ""
                self._token_expires_at = 0.0
                token = self._get_tenant_token()
                if not token:
                    return ""
                continue

            if attempt < self.max_retries - 1:
                logger.warning(
                    "创建记录失败(attempt %d/%d): code=%s",
                    attempt + 1,
                    self.max_retries,
                    data.get("code"),
                )
                time.sleep(self.backoff_base * (2**attempt))
            else:
                logger.error(
                    "创建记录失败: code=%s msg=%s",
                    data.get("code"),
                    data.get("msg", ""),
                )
                return ""

        return ""

    def _update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        """更新飞书 Bitable 中的一条记录。

        Args:
            record_id: 要更新的记录 ID。
            fields: 平坦字段字典。

        Raises:
            RuntimeError: 配置问题或重试耗尽。
        """
        if not self.app_token or not self.table_id:
            if self.bridge_mode:
                return self._bridge_update_record(record_id, fields)
            raise RuntimeError("app_token 和 table_id 不能为空")

        token = self._get_tenant_token()
        if self.bridge_mode and token == "bridge_placeholder":
            return self._bridge_update_record(record_id, fields)
        if not token:
            raise RuntimeError("无法获取 tenant_access_token")

        url = (
            f"{self.FEISHU_OPENAPI_BASE}/open-apis/bitable/v1/apps"
            f"/{self.app_token}/tables/{self.table_id}/records/{record_id}"
        )
        payload = {"fields": fields}

        import urllib.request
        import urllib.error

        for attempt in range(self.max_retries):
            body = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=body, method="PUT")
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", "application/json; charset=utf-8")

            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                logger.warning(
                    "更新记录失败(attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff_base * (2**attempt))
                continue

            if data.get("code") == 0:
                logger.info("更新记录成功: record_id=%s", record_id)
                return

            # token 过期时刷新
            if data.get("code") == 99991663:
                logger.info("token 已过期，正在刷新...")
                self._token = ""
                self._token_expires_at = 0.0
                token = self._get_tenant_token()
                if not token:
                    raise RuntimeError("无法刷新 tenant_access_token")
                continue

            if attempt < self.max_retries - 1:
                logger.warning(
                    "更新记录失败(attempt %d/%d): code=%s",
                    attempt + 1,
                    self.max_retries,
                    data.get("code"),
                )
                time.sleep(self.backoff_base * (2**attempt))
            else:
                raise RuntimeError(
                    f"更新记录失败: code={data.get('code')} msg={data.get('msg', '')}"
                )

        raise RuntimeError("更新记录失败: 已达最大重试次数")

    # ─── 桥接模式 ────────────────────────────────────────────

    def _bridge_create_record(self, fields: dict[str, Any]) -> str:
        """桥接模式：将创建写入 JSON 队列文件。"""
        os.makedirs(self._bridge_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        task_id = fields.get("task_id", "unknown")
        method = fields.get("method_name", "unknown")
        symbol = fields.get("symbol", "unknown")

        dedup_key = f"{task_id}_{method}_{symbol}"
        filename = f"{timestamp}_{dedup_key}.json"
        filepath = os.path.join(self._bridge_dir, filename)

        queue_entry = {
            "action": "create",
            "app_token": self.app_token,
            "table_id": self.table_id,
            "fields": fields,
            "dedup_key": dedup_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(queue_entry, f, ensure_ascii=False, indent=2)

        logger.info(
            "[BRIDGE] 写入队列文件: %s (action=create, key=%s)",
            filepath,
            dedup_key,
        )
        return f"rec_bridge_{timestamp}_{dedup_key}"

    def _bridge_update_record(self, record_id: str, fields: dict[str, Any]) -> None:
        """桥接模式：将更新写入 JSON 队列文件。"""
        os.makedirs(self._bridge_dir, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        task_id = fields.get("task_id", "unknown")
        method = fields.get("method_name", "unknown")
        symbol = fields.get("symbol", "unknown")

        dedup_key = f"{task_id}_{method}_{symbol}"
        filename = f"{timestamp}_{dedup_key}_update.json"
        filepath = os.path.join(self._bridge_dir, filename)

        queue_entry = {
            "action": "update",
            "app_token": self.app_token,
            "table_id": self.table_id,
            "record_id": record_id,
            "fields": fields,
            "dedup_key": dedup_key,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(queue_entry, f, ensure_ascii=False, indent=2)

        logger.info(
            "[BRIDGE] 写入队列文件: %s (action=update, key=%s)",
            filepath,
            dedup_key,
        )

    # ════════════════════════════════════════════════════════
    # schema 版本管理
    # ════════════════════════════════════════════════════════

    def get_schema_version(self) -> str:
        """当前 schema 版本。"""
        return self.SCHEMA_VERSION

    def upgrade_schema(self, new_version: str) -> bool:
        """升级 schema 版本。

        Args:
            new_version: 新版本号。

        Returns:
            bool: 升级成功返回 True。

        Raises:
            ValueError: 版本号无效（空字符串或等于当前版本）。
        """
        if not new_version:
            raise ValueError("新版本号不能为空")
        if new_version == self.SCHEMA_VERSION:
            raise ValueError(f"新版本号({new_version})与当前版本相同，无需升级")

        old_version = self.SCHEMA_VERSION
        type(self).SCHEMA_VERSION = new_version

        if self._simulate:
            logger.info(
                "[SIMULATE] schema 版本升级: %s → %s",
                old_version,
                new_version,
            )

        return True

    # ════════════════════════════════════════════════════════
    # 工具方法
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _json_dumps(obj: Any) -> str:
        if not obj:
            return "{}"
        return json.dumps(obj, ensure_ascii=False, default=str)

    @property
    def synced_count(self) -> int:
        return len(self._synced_keys)

    @property
    def retry_queue_size(self) -> int:
        return len(self._retry_queue)
