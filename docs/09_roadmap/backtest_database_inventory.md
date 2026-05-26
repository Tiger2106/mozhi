# 回测数据库清单与迁移方案

> **第四版修订**：2026-05-18 — 修正 knowledge.db 路径
> **第三版修订**：2026-05-18 — 修正路径/状态错误 + 采用 Owner Stage 1 结构
> **第二版修订**：2026-05-18 — 按长期路线重写 (per 墨涵 review)

> 作者: 墨衡 | 创建时间: 2026-04-29

---

## 一、总览

当前系统中散布着多个 SQLite 数据库文件，部分为历史遗留产物，部分为当前运行所需。本文件记录所有回测相关数据库的位置、用途及存在的冗余问题，并提供按长期目标架构推进的迁移方案。

**核心原则：所有数据库统一归入 `mozhi_platform/data/{domain}/`，一个 domain 一套库，不重复、不分散。冗余副本经确认引用链后删除，而非保留。**

---

## 二、当前数据库详细清单

### 2.1 行情数据库

| 名称 | 路径 | 用途 | 状态 |
|:-----|:-----|:-----|:-----|
| `analysis.db` | `C:\Users\17699\mo_zhi_sharereports\analysis.db`（**修正**：原 v3 误标为 `marketdata/` 子目录） | 存储 A 股日线 / 分钟线 OHLCV 行情数据 | 旧路径，**需迁移** |
| `market_data.db` | `C:\Users\17699\mozhi_platform\data\market\market_data.db` | 迁移目标库，已验证并入系统 | ✅ **目标位** |

**说明**：`analysis.db`（4.3MB）和 `market_data.db` 同源同构，数据存在冗余。`market_data.db` 为基础行情接入任务的目标库，`analysis.db` 中的行情数据应由其替代。

### 2.2 因子数据库

| 名称 | 路径 | 用途 | 状态 |
|:-----|:-----|:-----|:-----|
| `factor_repository.db` | `C:\Users\17699\mo_zhi_sharereports\factor_repository.db` | 因子值存储，当前仅存于 `mo_zhi_sharereports/` | 孤立，**待迁移** |

**说明**：因子库是投资研究核心资产，当前存储在临时目录下，未纳入平台统一管理。迁移目标：`mozhi_platform/data/factors/factor_repository.db`。

### 2.3 交易引擎数据库

| 名称 | 路径 | 用途 | 状态 |
|:-----|:-----|:-----|:-----|
| `trade_engine.db`（主库） | `C:\Users\17699\mo_zhi_sharereports\trade_engine.db`（94KB，当前唯一活跃数据源） | 当前交易引擎主库 | 🔧 **数据源**（目标库尚未初始化） |
| `trade_engine.db`（空壳） | `C:\Users\17699\mozhi_platform\data\trade_engine.db`（0KB） | 目标路径空壳，从未初始化 | 🔧 **待迁移** |
| `trade_engine_copy_*.db` (+ 副本) | 多处临时目录（详见下方明细） | 回测/调试产生的副本 | 🔧 **待清理** |

**⚠️ 事实修正**：原 v3 标注 `mozhi_platform/data/trade/trade_engine.db` 为"✅ 已在位"，但该路径为 0KB 空壳（未初始化数据）。当前唯一有数据的活跃库位于 `mo_zhi_sharereports/trade_engine.db`（94KB）。Owner 已将目标域名从 `trade/` 重命名为 `execution/`。

**trade_engine 副本明细表（v2 版保留）**：

| 类别 | 路径 | 大小 | 说明 |
|:-----|:-----|:----:|:-----|
| **活跃库（3 个）** | | | |
| | `mo_zhi_sharereports\trade_engine.db` | 94KB | 主库数据源 |
| | `mo_zhi_sharereports\trade_engine_readonly.db` | 94KB | 只读副本 |
| | `mo_zhi_sharereports\trade_engine_test_settlement.db` | 94KB | 测试结算副本 |
| **归档日期（5 个）** | | | |
| | `mo_zhi_sharereports\backup\trade_engine_20260510_233601.db` | 53KB | 2026-05-10 备份 |
| | `mo_zhi_sharereports\backup\trade_engine_20260512.db` | 57KB | 2026-05-12 备份 |
| | `mo_zhi_sharereports\backup\trade_engine_20260513.db` | 94KB | 2026-05-13 备份 |
| | `mo_zhi_sharereports\backup\trade_engine_20260514.db` | 94KB | 2026-05-14 备份 |
| | `mo_zhi_sharereports\backup\trade_engine_20260515.db` | 94KB | 2026-05-15 备份 |
| | `mo_zhi_sharereports\backup\db\trade_engine_20260510_233601.db` | 53KB | 2026-05-10 深备份 |
| **空壳路径（3 个）** | | | |
| | `mozhi_platform\data\trade_engine.db` | 0KB | 目标路径空壳 |
| | `mozhi_platform\data\trade_engine_20260515.db` | 0KB | 命名空壳 |
| | `mo_zhi_sharereports\data\trade_engine.db` | 0KB | 子目录空壳 |
| **历史残留（1 个）** | | | |
| | `mo_zhi_sharereports\mozhi_share_lib\...\phase2\trade_engine.db` | 61KB | phase 1→2 遗留 |

**说明**：扣除 3 个空壳后，实际有数据副本约 9 份（3 活跃 + 5 归档 + 1 历史残留），与 v2 所述"11 个副本"口径一致。先迁移主库数据至 `mozhi_platform/data/execution/trade_engine.db`，再清理所有冗余副本。

### 2.4 知识数据库

| 名称 | 路径 | 用途 | 状态 |
|:-----|:-----|:-----|:-----|
| `knowledge.db` | `C:\Users\17699\mozhi_platform\data\knowledge.db`（3.5MB, 9表, integrity PASS） | 投资知识库 | ✅ **已有** |

**说明**：知识数据库 `knowledge.db` 包含 9 张表（backtest_runs, performance_results, knowledge_entries, backtest_equity_series, market_context, params_snapshot, backtest_trades, knowledge_run_links），3.5MB，integrity 校验通过。

### 2.5 文件注册数据库

| 名称 | 路径 | 用途 | 状态 |
|:-----|:-----|:-----|:-----|
| `file_registry.db` | `C:\Users\17699\mozhi_platform\registry\file_registry.db`（**修正**：原 v3 误标为 `.openclaw/workspace-moheng/registry/`）（5.7MB, 7491 条记录） | 文件注册表，记录所有受管文件的路径、版本、校验和等信息 | ✅ **已在位**（迁移期需同步至 `data/registry/`） |

**说明**：文件注册表已投入使用，当前位于 `mozhi_platform/registry/`。目标架构归入 `data/registry/`，迁移期间需同步路径引用更新。

### 2.6 日历数据（整合至市场域）

| 名称 | 路径 | 用途 | 状态 |
|:-----|:-----|:-----|:-----|
| 日历数据（源 1） | 系统模块内嵌 | 交易日历主数据源 | 数据分散于两处 |
| 日历数据（源 2） | 独立日历文件 | 回测系统引用 | 需统一 |

**说明**：按 Owner Stage 1 结构，日历不设独立目录，归并入 `market/` 或 `knowledge/` 域。

---

## 三、冗余分析

### 3.1 行情数据库冗余

- **冗余数据库**：`analysis.db`（旧路径 `mo_zhi_sharereports/analysis.db`） ↔ `market_data.db`（目标路径）
- **冗余规模**：全量 A 股日线/分钟线数据（估计数百万条记录）
- **冗余类型**：同源副本
- **处理策略**：确认所有引用 `analysis.db` 的模块切换至 `market_data.db` 后，删除旧路径副本

### 3.2 交易引擎数据库冗余

- **冗余范围**：`mo_zhi_sharereports/trade_engine.db`（当前主数据源） + **11 个副本**（3 活跃 + 5 归档 + 3 空壳）
- **冗余规模**：9 份有数据副本 + 3 份空壳 = 12 个文件相关
- **冗余类型**：调试/测试残留 + 目标路径空壳
- **处理策略**：先迁移主库数据至 `data/execution/trade_engine.db`，再逐个确认副本引用来源后清理

### 3.3 日历数据分散

- **分散路径**：系统模块内嵌 + 独立日历文件
- **冗余类型**：逻辑分散而非物理冗余
- **处理策略**：统一归入 `market/` 或 `knowledge/` 域（不设独立日历目录）

---

## 四、目标架构总览图（Owner Stage 1）

```
mozhi_platform/data/
│
├── market/                  # 行情域
│   └── market_data.db       # ✅ 已在位
│
├── factors/                 # 因子域（Owner 命名：复数）
│   └── factor_repository.db # 🔧 新建（从 mo_zhi_sharereports/ 迁入）
│
├── research/                # 研究成果域（新增）
│   └── research.db          # 🔧 新建
│
├── execution/               # 交易执行域（替代原 trade/）
│   └── trade_engine.db      # 🔧 待迁移（数据在 mo_zhi_sharereports/）
│
├── knowledge/               # 知识域
│   └── knowledge.db         # ✅ 目标域已在位
│
└── registry/                # 文件注册域（替代原 file_registry/）
    └── file_registry.db     # 🔧 待迁入（当前在 mozhi_platform/registry/）
```

> 每个 domain 仅保留一套数据库，无冗余副本。历史路径和临时副本在确认引用链后删除。

**结构变更记录**：
| v2 域名 | v3/Stage 1 域名 | 说明 |
|:--------|:----------------|:-----|
| `trade/` | `execution/` | Owner 重命名 |
| `file_registry/` | `registry/` | 简化和标准化 |
| `factor/` | `factors/` | 复数形式 |
| — | `research/` | 新增域 |
| `calendar/` | （归并） | 不设独立目录 |

---

## 五、建议迁移路线

按照"长期目标架构"思路，所有步骤直接指向最终目标，不存在中间过渡态：

### 迁移动作一览

| 目标架构（Stage 1） | 当前差距 | 打通动作 |
|:-------------------|:---------|:---------|
| `market/market_data.db` ✅ 已在位 | `analysis.db` 旧路径仍有同源行情数据 | 确认所有引用 `analysis.db` 的模块切换到 `market_data.db`，删除 `analysis.db` |
| `factors/factor_repository.db` 🔧 新建 | 因子数据库仅存于 `mo_zhi_sharereports/factor_repository.db` | 复制因子数据到 `mozhi_platform/data/factors/factor_repository.db`，更新所有引用路径，删除旧路径副本 |
| `research/research.db` 🔧 新建 | 尚未建立 | 定义研究成果数据模型并建库 |
| `execution/trade_engine.db` 🔧 待迁移 | 目标路径空壳（0KB），数据在 `mo_zhi_sharereports/trade_engine.db` | 正确初始化目标库，导入数据，清理 11 个副本 |
| `knowledge/knowledge.db` ✅ 目标域已在位 | 需确认 `.db` 文件位置 | 确认或创建 `knowledge/knowledge.db` |
| `registry/file_registry.db` 🔧 待迁入 | 当前在 `mozhi_platform/registry/`，需迁至 `data/registry/` | 物理迁移 + 所有引用的路径更新 |
| 日历（归入 `market/` 或 `knowledge/`） | 数据分散于系统模块和独立文件两处 | 统一合并至选定的目标域 |

### 执行顺序

1. **市场行情迁移**（任务号：DB-MARKET）— 模块引用切换 + 旧库删除
2. **因子数据库迁移**（任务号：DB-FACTOR）— 复制数据 + 路径更新
3. **交易引擎数据迁移**（任务号：DB-TRADE-MIGRATE）— 初始化 `execution/trade_engine.db` + 导入主库数据
4. **交易日历统一**（任务号：DB-CALENDAR）— 合并至选定目标域
5. **文件注册表迁移**（任务号：DB-REGISTRY-MIGRATE）— 物理移至 `data/registry/` + 路径引用更新
6. **研究成果库建立**（任务号：DB-RESEARCH）— 新建 `research/research.db`
7. **交易引擎副本清理**（任务号：DB-TRADE-CLEAN）— 逐副本确认清理（`data/execution/` 就绪后执行）

> ⚠️ 所有动作均为一次性操作，无"先过渡再过渡"的中间态。每一步完成后，该 domain 即达到最终目标状态。

---

## 六、附录

### A. 引用模块清单

| 数据库 | 主要引用模块 | 引用方式 |
|:-------|:-----------|:---------|
| `market_data.db` | 行情服务、回测引擎 | 直接连接 |
| `analysis.db` | 旧版回测脚本、历史遗留工具 | 直接连接（需切换） |
| `factor_repository.db` | 因子计算、策略评估 | 直接连接 |
| `trade_engine.db` | 交易执行、回测调度 | 直接连接 |
| `knowledge.db` | RAG 查询、知识检索 | 应用层 API |
| `file_registry.db` | 文件生命周期管理 | 工具链调用 |

### B. 风险控制

- 每步迁移完成后执行回归验证：确认新库读写正常、业务模块运行无误
- 旧库保留 48 小时冷静期后再物理删除
- 副本清理前确认无进程持有文件句柄
- 各任务记录于 `file_registry.db` 以备追溯
