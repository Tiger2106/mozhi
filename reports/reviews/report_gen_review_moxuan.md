# 墨萱评审：Report Generator 接入方案 · 技术评审

> **评审人**: 墨萱 🔍  
> **日期**: 2026-05-16  
> **版本**: v1.0  
> **评审对象**:  
>   - `reports/backtest/report_generator_integration_plan.md`  
>   - `C:\Users\17699\Documents\BaiduSyncdisk\读书\python\backtest_report_generator.py`

---

## 1. 总体评价

**CONDITIONAL_PASS** ✅🟡

方案整体思路清晰，适配器设计与报告生成器解耦合理，管线接入点选择恰当。但存在 **1 个必须修复的设计问题** 和 **3 个需要明确的高风险点**，在修复前不应进入实施。

---

## 2. 核心问题

### 🔴 问题 1：`_load_price_data` 策略-标的代码映射缺失（严重）

**位置**: 方案文档附录伪代码 `_load_price_data` 方法（第 22−23 行在 _build 中被调用）

**问题**: 
```python
def _load_price_data(self, strategy_name: str):
    rows = self.db.execute("""
        SELECT date, close FROM stock_daily
        WHERE code = '601857'
        ORDER BY date DESC LIMIT 85
    """).fetchall()
```

`code = '601857'` 硬编码了。但根据数据库实际结构，`backtest_results` 表**没有** `code`（股票代码）字段。策略回测可能运行于不同标的（当前有 601857.SH、000001.SZ 等），适配器无法知道该为哪个标的拉取行情数据。

**影响**: 🟡 如果未来增加其他标的（如已存在的 grid_000001.SZ_* 回测），会拉取到错误的行情，导致以下错误链：
- `benchmark_nav` 使用错误标的收盘价计算
- `base_return` 和 `alpha` 完全错误
- 图表上的日期数据与策略实际交易不对齐

**修复要求**: 
- `backtest_results` 表必须新增 `code` 字段标识回测标的
- 或在 `strategy_name` 中编码标的（如已有做法 `grid_601857.SH_...`），适配器需解析
- 如果按文件名约定解析，适配器 `_build` 中需从 `row["strategy_name"]` 提取代码

---

### 🟡 问题 2：`total_trades` 字段在 `_derive_grade` 中被使用但缺失（中风险）

**位置**: 方案文档附录伪代码 `_derive_grade`（第 67−68 行）

```python
def _derive_grade(self, row) -> str:
    grade, _ = calc_t1_grade(
        row["sharpe_ratio"], row["max_drawdown"],
        row["win_rate"], row["total_trades"]
    )
```

**问题**: `backtest_results` 表确实有 `total_trades` 字段（见数据库 PRAGMA 结果），此处映射正确。但 `calc_t1_grade()` 函数（位于 `backtest_report_generator.py` 第 113−127 行）使用 `trade_count` 作为样本数判断。如果 `total_trades` 为 0 或 NULL，评级会直接降到 C 档"样本不足"——这是合理行为，但适配器未做 `None` 处理。

**风险**: `total_trades` 可能为 NULL（`nullable=0` 未指定，默认可空），适配器直接 `row["total_trades"]` 在 SQLite 中会返回 `None`，传给 `calc_t1_grade` 时 `trade_count < 20` 条件成立，所有策略都判 C 档。需做 `coalesce(row["total_trades"], 0)` 或 Python 侧空值处理。

---

### 🟡 问题 3：`_build` 中 `nav` 归一化存在除零风险（中风险）

**位置**: 方案文档附录伪代码 `_build` 方法（第 37 行）

```python
nav=[v / nav[0] for v in nav],
```

**问题**: 
1. 如果 `_load_equity_series` 返回空列表，`nav[0]` 会 IndexError
2. 如果 `nav[0]` 是 0.0（不可能但未检查），会 ZeroDivisionError

对 600+ 条回测来说，空净值序列的概率虽低但在数据库倾斜场景下是真实风险。

---

### 🔴 问题 4：`_load_price_data` 固定取 85 根 K 线，与回测实际日期范围可能不匹配（严重）

**位置**: 方案文档附录伪代码（第 23 行 `LIMIT 85`）

**问题**: 
- `LIMIT 85` 是硬编码的最近交易日数量
- 策略回测可能运行于不同的日期范围（如 600 日、3 年等）
- `backtest_results` 表有 `start_date`/`end_date` 字段，但适配器未使用
- 适配器应按 `start_date`/`end_date` 精确查询行情，而非固定 85 根

**影响**: 股价序列长度与净值序列 `backtest_equity_series` 长度不一致，会触发 `_validate_result` 的 `len(dates) != len(nav)` 校验异常。

---

### 🟢 问题 5：`signal_desc` 与 `params_desc` 字段映射可改进（低风险）

**位置**: 方案文档字段映射表 + 伪代码

**问题**:
- `signal_desc` 固定为 `"基于{strategy_name}信号触发"`，这个描述对报告展示来说信息量不足
- `params_desc` 用 `"; ".join(...)` 拼接参数，如果参数值包含 `=` 号会歧义（概率低但建议用 JSON 直接展示）

---

## 3. 改进建议

### A. `backtest_results` 表需新增字段或约定

**建议**: 新增 `code` TEXT NOT NULL 字段，存储标的代码（如 `601857.SH`、`000001.SZ`）。适配器按此字段精确查询行情数据。

或：如果希望避免 DDL 变更（方案中已说明不做 Schema 变更），那么回测运行方需在 `strategy_name` 中保证编码标的（如已有做法 `grid_601857.SH_...`），适配器从 `strategy_name` 正则提取。

### B. `_load_price_data` 应按日期范围查询

```python
def _load_price_data(self, start_date: str, end_date: str, code: str):
    rows = self.db.execute("""
        SELECT date, close FROM stock_daily
        WHERE code = ? AND date >= ? AND date <= ?
        ORDER BY date
    """, (code, start_date, end_date)).fetchall()
```

### C. `nav` 归一化加安全保护

```python
nav_vals = self._load_equity_series(row["id"])
if not nav_vals:
    nav_vals = [1.0]  # 降级：无法获取净值时使用单位净值
elif nav_vals[0] == 0:
    nav_vals = [1.0] + nav_vals[1:]  # 修复首个为 0 的情况
nav = [v / nav_vals[0] for v in nav_vals]
```

### D. trade_records 子表 DDL 建议

方案中提及但不包含 DDL。建议明确（供 Step1 之后参考）：

```sql
CREATE TABLE IF NOT EXISTS trade_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_id INTEGER NOT NULL REFERENCES backtest_results(id),
    buy_date TEXT NOT NULL,
    sell_date TEXT,
    buy_price REAL NOT NULL,
    sell_price REAL,
    shares INTEGER NOT NULL,
    pnl REAL,
    return_pct REAL,
    hold_days INTEGER,
    is_win INTEGER,
    signal TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
```

### E. HTML 临时文件路径的跨平台兼容性

**位置**: `backtest_report_generator.py` `_find_browser()` 方法（生成器代码）

Windows 路径硬编码（`C:\Program Files (x86)\Microsoft\...`）在开发机运行没有问题，但在未来容器化/云化环境中会崩溃。建议将浏览器路径提取为配置文件或环境变量：

```python
@staticmethod
def _find_browser() -> str:
    env = os.environ.get("REPORT_BROWSER_PATH")
    if env and os.path.isfile(env):
        return env
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    raise RuntimeError(...)
```

### F. `generate_pdf` 子进程超时应可配置

`subprocess.run(cmd, check=True, capture_output=True, timeout=60)` 的 60 秒硬编码在 Chart.js 渲染大数据量时可能不够。建议也可配置化。

### G. 报告文件命名中的策略组名应可配置

方案中 `{YYYYMMDD}_{策略组名}.html` 的"策略组名"目前未定义。假设今日有 3 个趋势 + 2 个反转 + 4 个网格，策略组名应如何确定？建议：
- 按 `backtest_results` 表中回测的 `strategy_name` distinct 列表拼接
- 或由上层调用方通过参数控制组名

---

## 4. 管线集成风险评价

### Step4.5 位置合理性 ✅

放在 Step4（墨萱审查）之后、Step5（发布）之前是正确选择。理由：
- 报告内容基于已锁定的晨报内容
- 墨萱的质检不影响报告生成逻辑
- 报告生成失败不应阻塞主发布流程（降级策略已明确）

### 新增依赖风险 🟡

| 依赖 | 风险等级 | 说明 |
|------|---------|------|
| `jinja2` | 🟢 | 报告中 `ReportGenerator` 手动构建 HTML，未使用 Jinja2（由 `__init__` 中提到但实际代码未使用） |
| `pandas`/`numpy` | 🟢 | `ReportGenerator` 中未使用，适配器也不依赖 |
| Chart.js CDN | 🟢 | 浏览器加载，不影响服务端 |
| Edge headless | 🟡 | 仅在 PDF 生成时使用，且已做异常捕获隔离 |
| `subprocess.run` timeout | 🟢 | 已设置 60s 超时且捕获异常 |

### CHART.JS CDN 离线风险 🟡

生成的 HTML 报告依赖 `https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js`。若内网环境打不开 CDN，图表区域会渲染失败。建议：
- **P2**: 增加 `fallback` 加载本地 Chart.js 副本
- **P3**: 在安装脚本中预下载 Chart.js 到本地静态资源目录

---

## 5. 测试覆盖建议

### 5.1 适配器单元测试（建议测试项）

| 测试用例 | 优先级 | 场景 | 验证点 |
|---------|--------|------|--------|
| 单条回测全字段映射 | P0 | 已知结果 + 完整 DB 数据 | 每个 StrategyResult 字段与预期一致 |
| 空净值序列 | P0 | equity_series 无数据 | 降级为单位净值 1.0，不抛 IndexError |
| 空行情数据 | P0 | stock_daily 无对应 code 的数据 | 返回空列表不影响适配器运行 |
| 参数格式异常 | P1 | parameters 字段存纯文本而非 JSON | `_format_params` 返回原文本 |
| 多策略批量读取 | P1 | 当日有 3 条回测 | 列表长度为 3，字段映射完整 |
| 无今日回测记录 | P1 | 无 created_at 今日的记录 | `get_today_results` 返回空列表 |
| stock_daily 日期对齐 | P2 | 交易日间隔 vs 净值序列 | dates 与 nav 等长 |
| total_trades 为 NULL | P1 | `_derive_grade` 输入 0 | C 档 + "样本不足" 说明 |
| 多标的回测 | P2 | 不同 code 的回测记录 | 每个回测拉取正确标的的行情 |

### 5.2 集成测试（建议测试项）

| 测试用例 | 优先级 | 场景 | 验证点 |
|---------|--------|------|--------|
| Step4.5 触发 | P0 | 模拟 REVIEW_READY 信号 | 适配器被调用 |
| HTML 文件生成 | P0 | 单策略 + 多策略 | 文件存在且包含正确的 ID/name |
| HTML 可被浏览器打开 | P1 | Chromium 直接打开 HTML | 无白屏/JS error |
| 报告生成失败降级 | P1 | 故意断网 / 删掉 analysis.db | 生成 FAILED 文件，Step5 继续 |
| 无新回测时跳过 | P1 | 无 today 记录 | 适配器不被调用 |
| PDF 输出 | P2 | Edge headless 可用 | PDF 文件生成且可打开 |

### 5.3 测试代价重估

方案中估算 **80 行** 测试代码，我重新评估：

| 模块 | 方案估算 | 墨萱评估 | 说明 |
|------|---------|---------|------|
| 适配器单元测试 | 40 行 | **60−80 行** | 缺少边界情况（空列表、NULL 字段、参数格式异常）的测试 |
| 管线集成测试 | 40 行 | **50−60 行** | mock DB + mock dispatcher 信号 + HTML 验证 + 降级验证 |
| **合计** | **80 行** | **110−140 行** | 差距约 30−60 行，主要是边界覆盖不足 |

**评估结论**: 测试代价估算偏低约 30−50%。建议按照 P0/P1 优先级分阶段完成。

---

## 6. 实施前必改清单（Gate 条件）

以下 4 项是 **CONDITIONAL_PASS** 的条件，均需在实施前修复或明确：

1. ✅ **标的代码映射** — `_load_price_data` 必须从数据库记录中准确获取标的代码，禁止硬编码
2. ✅ **日期范围对齐** — `_load_price_data` 必须按回测的 `start_date`/`end_date` 精确查询，禁止固定 `LIMIT 85`
3. ✅ **空净值序列保护** — `nav[0]` 除零保护、空列表保护
4. ✅ **total_trades NULL 处理** — `_derive_grade` 入口增加 `coalesce` 或空值判断

---

## 7. 附加观察（不需修复，供墨衡参考）

- `ReportGenerator` 类结构清晰，方法拆分粒度合理，`_validate_result` 存在是加分项
- `_escape_html` / `_escape_js_sq` 安全函数正确实现，无 XSS 风险
- `generate_pdf` 的临时文件 `finally` 清理正确，是良好实践
- HTML 暗色模式适配 (`prefers-color-scheme: dark`) 提升用户体验
- `render_single`/`render_full`/`render_comparison` 每个方法都单独 try-except 并生成错误 HTML —— 设计正确
- 适配器伪代码使用 `Path(__file__).parent.parent / "data" / "analysis.db"` 相对路径，部署时需要确认 DB 位置

---

**评审结论**: CONDITIONAL_PASS ✅🟡  
**条件**: 修复以上 4 项后自动升级为 PASS  
**建议实施顺序**: P0 修复（1−2 天）→ P0 测试（1 天）→ P1 管线集成（0.5 天）→ P1 边界测试（0.5 天）→ 交付验收
