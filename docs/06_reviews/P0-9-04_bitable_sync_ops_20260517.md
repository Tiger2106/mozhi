<!--
  author: 墨衡（MoHeng）
  task_id: P0-9-risk (doc 4/5)
  created: 2026-05-17 20:19 +08:00
  status: READY
  source: risk_action_plan_moheng_20260517.md §P0-9
-->

# P0-#9-04: BitableSync 运维手册（Plugin 开发者文档 4/5）

> **目标读者：** 运维（墨衡）
> **核心内容：** 飞书多维表格（Bitable）同步模块的配置、运行、排错
> **前置依赖：** 飞书开发者后台 → 应用权限 → `bitable:bitable` 已授权

---

## 1. 模块定位

**BitableSync** 是 KnowledgeBridge 的默认下游同步目标。回测结果按 `KnowledgeEntry v2` 格式写入本地 JSON 后，由 BitableSync 推送到飞书多维表格。

### 数据流

```
MethodBacktestRunner.run() → MethodResult
  ↓
KnowledgeBridge.harvest() → KnowledgeEntry (本地JSON)
  ↓
BitableSync.sync(entries) → 飞书Bitable记录
```

### 核心文件

| 文件 | 用途 |
|------|------|
| `src/backtest/engine/bitable_sync.py` | Bitable同步主模块 |
| `src/backtest/engine/bitable_schema.py` | Bitable表结构定义 |
| `scripts/e2e_bitable_sync.py` | E2E集成测试脚本 |
| `.env.bitable` | Bitable配置（app_token, table_id） |

---

## 2. 配置

### 2.1 环境变量

```ini
# .env.bitable (放在 mozhi_platform 根目录)
BITABLE_APP_TOKEN=DummyAppToken
BITABLE_TABLE_ID=tab_xxx
BITABLE_ENABLED=true
BITABLE_SYNC_INTERVAL_HOURS=24
```

### 2.2 配置代码

```python
# src/backtest/engine/bitable_sync.py
# 从环境变量读取配置:

import os
from dotenv import load_dotenv

load_dotenv(".env.bitable")

app_token = os.getenv("BITABLE_APP_TOKEN", "")
table_id = os.getenv("BITABLE_TABLE_ID", "")
enabled = os.getenv("BITABLE_ENABLED", "false").lower() == "true"
```

---

## 3. 运维操作

### 3.1 状态检查

```bash
# 检查Bitable连接是否正常
python -m src.backtest.engine.bitable_sync --check

# 输出示例:
# ✅ Bitable连接正常 (app_token=DummyAppToken, table=tab_xxx)
# 最近同步: 2026-05-17 14:42 +08:00 (12小时前)
# 待同步条目: 3
```

### 3.2 手动同步

```bash
# 全量同步（推送本地所有未同步条目）
python -m src.backtest.engine.bitable_sync --sync --mode full

# 增量同步（仅推送上次同步后的新条目）
python -m src.backtest.engine.bitable_sync --sync --mode incremental

# 指定同步目录
python -m src.backtest.engine.bitable_sync --sync --input-dir data/knowledge_entries_v2/
```

### 3.3 清空重同步

```bash
# 清空Bitable表后再全量推送（谨慎使用）
python -m src.backtest.engine.bitable_sync --reset --sync --mode full
```

---

## 4. Bitable 表结构

| 字段名 | 类型 | 说明 | 示例 |
|--------|:----:|------|------|
| `entry_type` | 单选 | 条目类型 | `backtest_signal` |
| `symbol` | 文本 | 标的代码 | `601857` |
| `method_name` | 文本 | 方法名 | `macd` |
| `generated_at` | 日期时间 | 生成时间 | `2026-05-17T14:42:43+08:00` |
| `n_bars` | 数字 | 数据条数 | 120 |
| `n_signals` | 数字 | 信号条数 | 45 |
| `signal_ratio` | 百分比 | 信号占比 | 37.5% |
| `dominant_signal` | 文本 | 主导方向 | `BUY` |
| `config_json` | 文本 | 配置参数(JSON) | `{"fast": 12}` |
| `duration_ms` | 数字 | 执行耗时 | 12.3 |
| `notes` | 文本 | 备注 | 自动同步 |

---

## 5. 告警/监控

### 5.1 同步失败默认行为

```python
if not sync_result.success:
    logger.warning(
        "Bitable同步失败: %s (重试次数: %d, 下次重试: %s)",
        sync_result.error,
        sync_result.retry_count,
        sync_result.next_retry.isoformat(),
    )
```

- 默认自动重试 2 次（间隔 5 分钟）
- 2 次均失败后丢弃（不影响 Runner 执行）
- 触发飞书群告警（如果配置了告警 Webhook）

### 5.2 开启告警

```python
bridge = KnowledgeBridge(
    sync_to_bitable=True,
    alert_on_failure=True,
    alert_webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/xxx",
)
```

---

## 6. 常见故障处理

| 症状 | 原因 | 解决方案 |
|------|------|---------|
| `bitable_sync` 连接超时 | Bitable未授权或飞书API异常 | 1. `python -m .bitable_sync --check` 测试连接<br>2. 检查 `.env.bitable` 配置<br>3. 确认飞书应用 `bitable:bitable` 权限已开通 |
| 同步条目为0 | 输入目录为空或扫描错路径 | 1. 检查 `--input-dir` 路径<br>2. 确认 KnowledgeEntry v2 文件存在<br>3. 检查文件命名是否符合 `knowledge_*.json` |
| 部分字段值丢失 | Bitable字段类型不匹配 | 1. 执行 `python -m .bitable_sync --check` 查看字段schema<br>2. 对照 §4 表结构检查类型一致性<br>3. 若数据类型不匹配，手动调整Bitable字段类型 |
| 重复记录 | 断点续传未生效 | 1. 检查本地 `.sync_state.json` 文件<br>2. 手动清理 Bitable 重复行<br>3. 下次增量同步会自动跳过已同步条目 |
| Bitable表不存在 | app_token/table_id变更 | 1. 在飞书工作台确认Bitable URL<br>2. 更新 `.env.bitable` 中的 `BITABLE_APP_TOKEN` 和 `BITABLE_TABLE_ID` |

---

## 7. 依赖与阻塞

| 依赖 | 状态 | 说明 |
|------|:----:|------|
| `bitable_sync.py` | ✅ E2E通过 | 读写分离，可本地测试 |
| `bitable_schema.py` | ✅ 已定义 | 字段映射配置 |
| `.env.bitable` 配置 | ⏳ 待填写 | app_token 和 table_id 需上线前填入 |
| 飞书 App 权限 `bitable:bitable` | ⏳ 待开通 | 需在飞书开发者后台申请 |
| Bitable URL/ID | ⏳ 待创建 | 需在飞书工作台手动创建表 |

**阻塞路径：** 飞书权限开通 + Bitable创建 → .env.bitable 配置 → E2E验证

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 20:19 +08:00*
