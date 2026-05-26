# 文件生命周期系统使用手册

author: 墨涵  
created_time: 2026-05-15T20:10:00+08:00  
version: v1.0  
based_on: file_lifecycle.py v3

---

## 一、系统概述

本系统管理墨枢平台所有文件的生命周期，从进入仓库到归档退役。

```
incoming/                正式目录                archive
   ↓                        ↓                      ↓
  新文件 → 登记入库 → 整理归类 → 变更追踪 → 归档退役
              ↓               ↓                    ↓
         file_registry.db  更新状态              标记archived
```

## 二、数据库位置

```
C:\Users\17699\mozhi_platform\registry\file_registry.db
```

## 三、数据库表结构

### 3.1 完整DDL

> ⚠️ 这是逻辑定义，DDL层面为宽松 TEXT（可空）。应用层代码保证必填字段非空。

```sql
CREATE TABLE files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT,               -- 文件名（逻辑必填）
    original_path TEXT,               -- 首次出现的完整路径，永不修改（逻辑必填）
    current_path  TEXT,               -- 当前所在路径，随移动更新（逻辑必填）
    category      TEXT,               -- 业务归属（逻辑必填）
    source        TEXT,               -- 来源仓库（逻辑必填）
    status        TEXT,               -- 生命周期阶段（逻辑必填）
    checksum      TEXT,               -- SHA256摘要
    source_type   TEXT,               -- 生成来源（逻辑必填）
    created_at    TEXT,               -- 文件创建时间
    imported_at   TEXT,               -- 登记入库时间
    tags          TEXT,               -- 逗号分隔标签
    note          TEXT                -- 自动摘要/备注
);

-- 索引（已建立）
CREATE UNIQUE INDEX IF NOT EXISTS idx_files_original_path ON files(original_path);
CREATE INDEX IF NOT EXISTS idx_files_filename      ON files(filename);
CREATE INDEX IF NOT EXISTS idx_files_current_path  ON files(current_path);
CREATE INDEX IF NOT EXISTS idx_files_category      ON files(category);
CREATE INDEX IF NOT EXISTS idx_files_source        ON files(source);
CREATE INDEX IF NOT EXISTS idx_files_status        ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_source_type   ON files(source_type);
```

### 3.2 字段参考

| 列 | 类型 | 说明 | 枚举值 |
|:---|:----|:-----|:-------|
| id | INTEGER | 自增主键 | — |
| filename | TEXT | 文件名 | — |
| original_path | TEXT | **首次出现的完整路径，永不修改** | — |
| current_path | TEXT | 当前所在路径 | — |
| category | TEXT | 业务归属 | `automation` `backtest` `reports` `docs` `signals` `tools` `db` `agents` `shared` |
| source | TEXT | 来源仓库 | `incoming` `platform` `archive` |
| status | TEXT | 生命周期阶段 | `incoming` `experimental` `staging` `production` `deprecated` `archived` |
| checksum | TEXT | SHA256 摘要 | 64字符hex |
| source_type | TEXT | 生成来源 | `ai_chatgpt` `ai_deepseek` `manual` `imported` `migrated` `unknown` |
| created_at | TEXT | 文件创建时间 | ISO8601 |
| imported_at | TEXT | 登记入库时间 | ISO8601 |
| tags | TEXT | 逗号分隔标签 | 自由填写 |
| note | TEXT | 自动摘要/备注 | py→注释, md→标题, json→description |

## 三-B：直接SQL查询（高级用户）

数据库是标准 SQLite，支持完整 SQL 语法。可用任意 SQL 客户端（DBeaver/DataGrip/SQLiteBrowser）或命令行直接查询。

### 连接数据库

```powershell
sqlite3 C:\Users\17699\mozhi_platform\registry\file_registry.db
```

或在 Python 中：

```python
import sqlite3
conn = sqlite3.connect(r'C:\Users\17699\mozhi_platform\registry\file_registry.db')
```

### 常用SQL示例

**1. 按分类统计文件数**
```sql
SELECT category, COUNT(*) AS cnt
FROM files
GROUP BY category
ORDER BY cnt DESC;
```

**2. 按来源统计**
```sql
SELECT source, COUNT(*) AS cnt
FROM files
GROUP BY source;
```

**3. 查看某个分类下的全部文件**
```sql
SELECT filename, current_path, status, checksum
FROM files
WHERE category = 'automation'
ORDER BY filename;
```

**4. 查找滞留 incoming 未整理的文件**
```sql
SELECT filename, current_path, created_at, note
FROM files
WHERE source = 'incoming' AND status = 'incoming'
ORDER BY created_at;
```

**5. 搜索文件内容摘要**
```sql
SELECT filename, category, note
FROM files
WHERE note LIKE '%结算%' OR note LIKE '%修复%';
```

**6. 查找最近7天新增的文件**
```sql
SELECT filename, category, source_type, imported_at
FROM files
WHERE imported_at > date('now', '-7 days')
ORDER BY imported_at DESC;
```

**7. 查找所有AI生成的文件**
```sql
SELECT filename, category, current_path, note
FROM files
WHERE source_type IN ('ai_deepseek', 'ai_chatgpt')
  AND status != 'archived';
```

**8. 按标签查找**
```sql
SELECT filename, tags, current_path
FROM files
WHERE tags LIKE '%cron%' AND tags LIKE '%晨报%';
```

**9. 文件去重检查（相同SHA256）**
```sql
SELECT checksum, COUNT(*) AS copies, GROUP_CONCAT(filename) AS files
FROM files
WHERE checksum != ''
GROUP BY checksum
HAVING copies > 1;
```

**10. 孤儿文件检测（DB存在但路径已不存在）**
```sql
SELECT filename, current_path
FROM files
WHERE status != 'archived';
-- 然后用 Python/os.path.exists 逐一验证
```

**11. 查看某一天的入库明细**
```sql
SELECT filename, category, source_type, status
FROM files
WHERE date(imported_at) = '2026-05-15';
```

**12. 组合查询：活着的db相关文件**
```sql
SELECT filename, current_path, note
FROM files
WHERE category = 'db'
  AND status NOT IN ('archived', 'deprecated');
```

## 四、命令手册

所有命令从 `mozhi_platform/` 目录下执行。

### 4.1 搜索文件

```powershell
cd C:\Users\17699\mozhi_platform

# 按文件名模糊搜索
python -m src.utils.file_lifecycle search --filename "grid"

# 按标签搜索
python -m src.utils.file_lifecycle search --tag "cron"

# 按分类搜索
python -m src.utils.file_lifecycle search --category "backtest"

# 按来源仓库搜索
python -m src.utils.file_lifecycle search --source "archive"

# 按生成来源搜索
python -m src.utils.file_lifecycle search --source-type "migrated"

# 按关键词搜索（匹配文件名/标签/备注）
python -m src.utils.file_lifecycle search --keyword "settlement"

# 组合条件搜索
python -m src.utils.file_lifecycle search --category "db" --status "archived"

# JSON格式输出
python -m src.utils.file_lifecycle search --filename "pipeline" --json
```

### 4.2 查看数据库统计

```powershell
cd C:\Users\17699\mozhi_platform
python -m src.utils.file_lifecycle status
```

输出内容：
- 总记录数
- 按来源分布（incoming / platform / archive）
- 按状态分布（incoming / archived / ...）
- 按分类分布（automation / backtest / ...）
- 最近7天新增趋势

### 4.3 更新文件状态（墨涵专用）

当 incoming 文件整理到正式目录后：

```powershell
python -m src.utils.file_lifecycle update ^
    --path "incoming/20260515/fix_settlement.py" ^
    --current-path "automation_v2/fix_settlement.py" ^
    --status "production" ^
    --category "automation" ^
    --tags "fix,settlement" ^
    --source-type "ai_deepseek" ^
    --note "修复结算模块KeyError"
```

参数说明：
| 参数 | 必填 | 说明 |
|:-----|:----:|:------|
| `--path` | ✅ | 记录在DB中的 original_path |
| `--current-path` | ✅ | 更新后的完整路径 |
| `--status` | ❌ | 新状态 |
| `--category` | ❌ | 新分类 |
| `--tag` | ❌ | 逗号分隔标签 |
| `--source-type` | ❌ | 生成来源 |
| `--note` | ❌ | 备注 |

### 4.4 数据库初始化

```powershell
# 初始化数据库（创建表+索引）
python -m src.utils.file_lifecycle init

# 强制重建（DROP + CREATE，清空所有数据）
python -m src.utils.file_lifecycle init --force
```

> ⚠️ `init --force` 会清空全部数据。重建后需重新运行 `archive-scan` 导入旧仓库索引。

### 4.4 扫描旧仓库（一次性）

```powershell
# 实际扫描（写入数据库）
python -m src.utils.file_lifecycle archive-scan

# 试运行（只看结果不写入）
python -m src.utils.file_lifecycle archive-scan --dry-run
```

### 4.6 daily-maintenance（墨涵每日执行）

```powershell
# 扫描incoming + 自动补meta.json + 登记数据库（当天）
python -m src.utils.file_lifecycle daily-maintenance

# 指定日期
python -m src.utils.file_lifecycle daily-maintenance --date 20260515

# 试运行
python -m src.utils.file_lifecycle daily-maintenance --dry-run
```

> `daily-maintenance` = `incoming_meta.py`(生成meta) + `register-incoming`(登记DB) 的合并快捷命令。

### 4.7 扫描异常检测

```powershell
# 扫描incoming + 自动补meta.json + 登记数据库
python -m src.utils.file_lifecycle daily-maintenance

# 指定日期
python -m src.utils.file_lifecycle daily-maintenance --date 20260515

# 试运行
python -m src.utils.file_lifecycle daily-maintenance --dry-run
```

### 4.6 扫描异常检测

```powershell
# 检测孤儿文件（DB存在但物理删除）
python -m src.utils.file_lifecycle scan-registry

# 导出全量CSV
python -m src.utils.file_lifecycle export --output "D:\backup.csv"
```

## 五、文件生命周期各阶段说明

```
incoming → experimental → staging → production → deprecated → archived
```

| 阶段 | 含义 | 存放位置 | 谁可以设置 |
|:-----|:-----|:---------|:----------|
| incoming | 刚进入缓冲区，未分类 | `incoming/YYYYMMDD/` | 自动 |
| experimental | 实验性代码 | `experiments/` | 墨衡/墨涵 |
| staging | 测试中 | `tests/` 或 `staging/` | 墨衡 |
| production | 正式投入运行 | `automation_v2/` `src/` | 墨涵 |
| deprecated | 不再使用但保留 | 原位标注 | 墨涵 |
| archived | 归档退役 | `archive/` | 墨涵 |

## 六、分类说明

### 6.1 分类映射规则（5级fallback）

```
1. 精确匹配目录名 → CATEGORY_MAP
2. 关键词匹配（如 ta_ → backtest）
3. 关键词匹配（如 601857_ → reports）
4. 目录名本身是否属于9分类枚举
5. 以上均不匹配 → shared
```

### 6.2 完整映射表

| 目录名 | → 分类 |
|:-------|:-------|
| automation_v2, pipeline, phase1_core, phase_2_2_adapter, scheduler, bots, code, workflows | **automation** |
| backtest_engine, backtest_results, tests, test_sandbox, unit_tests, experiments | **backtest** |
| reports, report-pipeline, reviews, daily, hotspot, 601857-analysis, oil-price-monitor | **reports** |
| docs, p0_tasks | **docs** |
| signals, eventbus | **signals** |
| scripts, tools, config, skills, deploy, collectors, token-optimizer, ui, xuanzhi_merge, cache_manager | **tools** |
| data, db, pgsql, data_warehouse | **db** |
| agents | **agents** |
| archive, comm_status, logs, runtime, shared, memory, meeting, templates, locks, rollback, signons, lib, knowledge_base, incoming, workspace-mochen, mozhi_share_lib | **shared** |

## 七、搜索技巧

### 找文件

```powershell
# 找"网格"相关文件
python -m src.utils.file_lifecycle search --filename "grid"

# 找所有cron配置
python -m src.utils.file_lifecycle search --tag "cron"

# 找最近入库的文档
python -m src.utils.file_lifecycle search --category "docs" --source "archive"

# 找未被整理的 incoming 文件
python -m src.utils.file_lifecycle search --source "incoming" --status "incoming"
```

### 看统计

```powershell
# 全部统计
python -m src.utils.file_lifecycle status

# 想看某类有多少文件 → status 查看 Category dist 段
# 想看哪些文件还没整理 → search --source "incoming"
```

## 八、日常维护流程（墨涵每天02:00）

```
step 1: daily-maintenance        → 扫描 incoming + 登记DB
step 2: 手动整理 incoming 文件     → copy到正式目录
step 3: update --path ...         → 更新DB状态
step 4: status                    → 确认整理完成
```

### 异常情况处理

| 情况 | 处理方法 |
|:-----|:---------|
| 数据库损坏/Cannot open | `init --force` 重建，然后重新 `archive-scan` |
| 孤儿文件（DB有记录但被删了） | `scan-registry` 查出后 `DELETE FROM files WHERE` |
| 文件放错分类 | `update --path "..." --category "正确分类"` |
| 重复登记 | `search --filename "xxx"` 确认已有后再决定是否去重 |

## 九、关联文档

| 文档 | 位置 |
|:-----|:------|
| 系统审查报告 | `docs/08_history/review_file_lifecycle_20260515.md` |
| Cron排程总览 | `docs/06_operations/cron_schedule.md` |
| 信号协议 | `docs/05_protocols/signal_schema.md` |
