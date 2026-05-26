<!--
  author: 墨衡（MoHeng）
  task_id: P0-9-risk (doc 5/5)
  created: 2026-05-17 20:19 +08:00
  status: READY
  source: risk_action_plan_moheng_20260517.md §P0-9
-->

# P0-#9-05: 快速排错手册（Plugin 开发者文档 5/5）

> **目标读者：** 所有开发者/运维
> **核心内容：** 15种常见问题的根因定位 + 修复步骤
> **格式：** 问题 → 症状 → 根因 → 排查命令 → 修复

---

## 1. 回测/运行类

### 1.1 `discover_methods()` 返回空列表

| 项目 | 内容 |
|------|------|
| **症状** | `MethodBacktestRunner` 抛 `ValueError("未知方法 'xxx'")` |
| **根因** | 文件名不符合自动发现规则 |
| **排查** | ```bash
ls src/backtest/methods/**/*.py    # 检查文件名
# 要求: 文件名必须以 _method.py 结尾
# 正确: ma_cross_method.py
# 错误: macross.py
``` |
| **修复** | 重命名文件为 `{name}_method.py` |
| **预防** | 创建新 Method 时使用 `plugin_dev_guide.md` §2.2 模板 |

### 1.2 `discover_methods()` 找到但无法实例化

| 项目 | 内容 |
|------|------|
| **症状** | `TypeError: Can't instantiate abstract class ...` |
| **根因** | `generate_signal()` 或 `on_bar()` 未实现 |
| **排查** | ```bash
python -c "from backtest.methods.xxx import XxxMethod; help(XxxMethod.generate_signal)"
# 确认不是 <abstractmethod>
``` |
| **修复** | 实现所有抽象方法。具体参考 `plugin_dev_guide.md` §2.2 模板 |
| **预防** | 开发时使用 IDE 的类型检查，确保 `setup()` + `generate_signal()` + `cleanup()` 三者实现 |

### 1.3 回测结果 NaN 泛滥

| 项目 | 内容 |
|------|------|
| **症状** | Method 信号全是 NaN 或 0 |
| **根因** | `data_min_bars` 不足导致前 N 行无有效计算 |
| **排查** | ```bash
# 打印信号列
python -c "
from backtest.methods.xxx import XxxMethod
import numpy as np
print(np.sum(np.isnan(result['signal'])))
print('NaN 行:', np.where(np.isnan(result['signal']))[0][:10])
" | ```
| **修复** | 1. 增加 `df` 数据长度（> method.required_bars）<br>2. 或在 `generate_signal()` 中用 `fillna(0)` |
| **预防** | METHOD_META 中声明 `data_min_bars`，预检逻辑 `R1` 会提示 |

### 1.4 MethodResult 信号值域异常

| 项目 | 内容 |
|------|------|
| **症状** | 信号值包含 2, -2, 0.5 等非常规值 |
| **根因** | `generate_signal()` 未归一化到 {-1, 0, 1} |
| **排查** | ```bash
python -c "
import numpy as np
unique = np.unique(result['signal'])
print('值域:', unique)
" | ```
| **修复** | 在返回前 clip: `result['signal'] = np.clip(result['signal'], -1, 1).astype(int)` |
| **预防** | 开发时在 `generate_signal()` 末尾加 `assert set(result['signal'].unique()).issubset({-1, 0, 1})` |

### 1.5 跑回测时 Runner 耗时过长 (>1s/10K bars)

| 项目 | 内容 |
|------|------|
| **症状** | 回测超时或 `duration_ms > 1000` |
| **根因** | `on_bar()` 或 `generate_signal()` 内有 O(n²) 操作（如 `for row in df.iterrows()` 嵌套循环） |
| **排查** | ```bash
# 打开日志监控:
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
# ... 运行回测
# 查看每步耗时
" | ```
| **修复** | 1. `on_bar()` 中避免 O(n²) — 推荐批量 DataFrame 操作<br>2. `generate_signal()` 使用向量化操作（底层 numpy）<br>3. 如需逐Bar复杂计算 → 声明 `requires_state=True` |
| **预防** | METHOD_META 中设置 `data_min_bars` 控制输入规模 |

---

## 2. 信号/交易类

### 2.1 信号桥失败：KnowledgeBridge 报错

| 项目 | 内容 |
|------|------|
| **症状** | 日志出现 `WARNING [knowledge_bridge] harvest failed: xxx` |
| **根因** | MethodResult 缺少关键字段（method_name、symbol 等）或 KnowledgeEntry v2 序列化失败 |
| **排查** | ```bash
# 检查 MethodResult 字段
python -c "
print(result.method_name, result.params)
# 检查必填项: signals, indicators (可选), method_name, params
" | ```
| **修复** | Runner 返回的 MethodResult 确保所有字段非空 |
| **预防** | 此错误不会阻止回测继续。但建议在开发环境跑：`pytest tests/test_knowledge_bridge.py` |

### 2.2 Bitable 同步失败

| 项目 | 内容 |
|------|------|
| **症状** | `logger.warning("Bitable同步失败: ...")` |
| **根因** | 见 `P0-9-04_bitable_sync_ops.md` §6 |
| **排查** | ```bash
python -m src.backtest.engine.bitable_sync --check
``` |
| **修复** | 按 bitable_sync_ops.md §6 排查 |
| **预防** | 配置 `.env.bitable` 后运行 E2E 测试 |

### 2.3 回测结果写入未产出 / 写错位置

| 项目 | 内容 |
|------|------|
| **症状** | `data/knowledge_entries_v2/` 下无预期 JSON 文件 |
| **根因** | 路径错误或 `enable_knowledge_collection=False` |
| **排查** | ```bash
# 检查是否启用了知识收割
grep -r "enable_knowledge_collection" src/backtest/runners/
# 检查输出目录
ls -la data/knowledge_entries_v2/
``` |
| **修复** | 1. `MethodBacktestRunner(..., enable_knowledge_collection=True)`<br>2. `run(df, harvest=True)` |
| **预防** | 确认 `harvest=True` 参数传入 |

### 2.4 文件写入后无验证

| 项目 | 内容 |
|------|------|
| **症状** | 文件写入了但内容为空或损坏 |
| **根因** | 写文件后没有用 `read` 回读验证 |
| **排查** | ```bash
# 检查文件大小和内容
ls -la data/knowledge_entries_v2/*.json
for f in data/knowledge_entries_v2/*.json; do
    python -c "import json; json.load(open('$f'))" || echo "$f 损坏"
done
``` |
| **修复** | 删除空文件，重跑。或手动写入验证逻辑 |
| **预防** | 始终遵循「写→读→验证」三步骤 |

---

## 3. 文件操作类

### 3.1 `.done` / `.failed` 信号文件冲突

| 项目 | 内容 |
|------|------|
| **症状** | **墨枢**流水线卡住，`dispatcher.py` 反复尝试 |
| **根因** | `.done` 和 `.failed` 同时存在，或都没写 |
| **排查** | ```bash
ls C:\Users\17699\mo_zhi_sharereports\signals\tasks\*_moheng.{done,failed} 2>nul
# 正常: 最多只有一个文件存在
``` |
| **修复** | 删除互斥的 `.done` 或 `.failed`，留一个 |
| **预防** | 只写 `.done` 或 `.failed` 之一，完成后立即 read 验证 |

### 3.2 写入后 read 验证失败

| 项目 | 内容 |
|------|------|
| **症状** | 文件写了但 read 为空 / 不存在 |
| **根因** | 写入路径不正确 或 文件系统尚未刷盘 |
| **排查** | ```bash
# 检查实际路径
ls C:\Users\17699\mozhi_platform\docs\06_reviews\
``` |
| **修复** | 确认路径参数正确，等待 2s 后重试 read |
| **预防** | 写入后立刻 read。若连续 3 次失败，写 `.failed` 文件并退出 |

### 3.3 Windows 路径转义问题

| 项目 | 内容 |
|------|------|
| **症状** | `FileNotFoundError` 或 `PermissionError` |
| **根因** | Windows 反斜杠被 Python 当转义符处理 |
| **修复** | 使用原始字符串 `r"C:\Users\xxx"` 或正斜杠 `C:/Users/xxx/` |
| **预防** | 统一使用正斜杠（如 `C:/Users/17699/mo_zhi_sharereports/...`） |

---

## 4. 格式/版本类

### 4.1 METHOD_META 校验失败

| 项目 | 内容 |
|------|------|
| **症状** | `validate_manifest()` 返回非空 error 列表 |
| **修复** | 参考 `manifest.py` 补全缺失字段。特别注意 `capabilities` 的三个 bool 子字段 |
| **排查** | ```python
from backtest.methods.manifest import validate_manifest
errors = validate_manifest(YOUR_METHOD.METHOD_META)
print(errors)
``` |
| **预防** | METHOD_META 中填写所有必填字段后再开发 |

### 4.2 Signal Schema 版本不兼容

| 项目 | 内容 |
|------|------|
| **症状** | KnowledgeEntry v1 vs v2 不兼容，Bitable 字段对应错误 |
| **修复** | `KnowledgeNormalizer` 中检查 `entry_type` 字段，确保输出格式与 Bitable schema 匹配 |
| **预防** | 统一使用 KnowledgeEntry v2 格式 |

---

## 5. 依赖和环境类

### 5.1 Python 依赖缺失

| 项目 | 内容 |
|------|------|
| **症状** | `ModuleNotFoundError: No module named 'xxx'` |
| **排查** | ```bash
pip list | findstr xxx
``` |
| **修复** | ```bash
pip install xxx
``` |
| **预防** | 新依赖添加到 `requirements.txt` |

### 5.2 系统时区不一致

| 项目 | 内容 |
|------|------|
| **症状** | 时间戳与 +08:00 不一致 |
| **排查** | ```bash
python -c "from datetime import datetime; print(datetime.now())"
``` |
| **修复** | `os.environ["TZ"] = "Asia/Shanghai"` 或 `pd.Timestamp.now(tz="Asia/Shanghai")` |
| **预防** | 始终使用 `pd.Timestamp.now(tz="Asia/Shanghai")`，不依赖系统时区 |

---

## 6. 排错流程总览

```
问题出现
  │
  ├──→ 日志在哪？
  │      └── logger.warning 在 stderr
  │
  ├──→ 文件在哪？
  │      └── 输出在 docs/06_reviews/ 或 data/knowledge_entries_v2/
  │
  ├──→ 依赖是什么？
  │      └── 检查 .env.bitable, METHOD_META, requirements.txt
  │
  └──→ 如何验证？
         └── pytest, e2e script, read 验证
```

---

## 7. 排错命令速查

| 场景 | 命令 |
|------|------|
| 测试Method可用性 | `python -c "from backtest.methods.xxx import XxxMethod; m = XxxMethod(); print('OK')"` |
| 检查Bitable连接 | `python -m src.backtest.engine.bitable_sync --check` |
| 查看回测日志 | `grep -i "runner" logs/backtest_latest.log` |
| 验证信号值域 | `python -c "import numpy as np; print(np.unique(result['signal']))"` |
| 检查文件完整性 | `python -c "import json; json.load(open('path/to/file.json'))"` |
| 显示心跳状态 | `python -m moheng_heartbeat list` |
| 查看信号文件 | `ls C:\Users\17699\mo_zhi_sharereports\signals\tasks\*_moheng.*` |
| 检查Bitable字段 | `python -m src.backtest.engine.bitable_sync --check --verbose` |

---

*墨衡 🖋️ | 深度投资专家 | 2026-05-17 20:19 +08:00*
