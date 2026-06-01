# 审查报告：task_01 — supplenment_survey.py

- **审查人**: 墨萱
- **审查时间**: 2026-05-29T21:56+08:00
- **审查对象**: `docs/07_research/A50截面IC/supplenment_survey.py`
- **设计版本**: design_v2 §5.1

---

## 审查结论：**PASS （需修复1个Bug）**

---

## 审查明细

### 1. SQL查询逻辑 ✅

| 查询 | 结果 | 备注 |
|:----|:----:|:------|
| Q1: pe/pb/float_share 缺失率 | ✅ 正确 | `MAX(COUNT(1),1)` 在 SQLite 中可通过（语法兼容），50支股票全部pe/pb/total_share 100%缺失，float_share ~62.62%缺失 |
| Q2: min_stocks截面覆盖率 | ✅ 正确 | 4710交易日，4550日可用≥30（覆盖率96.6%），最小23支，最大50支 |
| Q3: 复权方向验证 | ✅ 正确 | 贵州茅台 adj_factor 在20230630变化（非任务指定20230613），代码自动检测并正确分析 |
| Q4: 停牌日统计 | ✅ 正确 | 查询语法正确，返回0条记录（数据库中`close IS NULL`停牌记录数为0） |

SQLite schema 确认所有涉及字段（pe, pb, float_share, total_share, adj_factor, pre_close, change, pct_chg, volume）均存在且类型匹配。

### 2. 复权方向验证逻辑 ✅

- **公式**: `close * adj_factor` = 后复权，`close / adj_factor` = 前复权
- **方法**: 自动检测 adj_factor 变化日（>0.1%阈值），验证变化前后的连续性
- **实盘数据验证**: 
  - adj_factor 变化日: 20230630（7.651 → 7.768，+1.53%）
  - 后复权变化率: **0.18%**（连续 ✅）
  - 前复权变化率: **2.81%**（跳变 ❌）
- **结论**: 该数据库存储 **后复权 adj_factor**，`close * adj_factor` 产生连续价格序列
- **逻辑合理性判定**: 方法成熟，阈值0.1%合理（过滤舍入误差），自动检测优于硬编码日期

### 3. 代码质量

| 检查项 | 评级 | 说明 |
|:------|:----:|:------|
| DB路径存在性检查 | ✅ | `get_conn()` 中检查文件存在，不存在则 `sys.exit(1)` |
| 参数化查询 | ✅ | Q3使用 `?` 占位符，无SQL注入风险 |
| 路径处理 | ✅ | 使用 `os.path.join`，无硬编码斜杠 |
| 数据库连接关闭 | ⚠️ | 在 `main()` 末尾 `conn.close()`，但没有 try-finally，异常时连接泄漏 |
| SQL执行异常处理 | ❌ | 无任何 try-except 包裹 SQL 执行，查询异常直接崩溃且无法关闭连接 |
| 日志/输出 | ⚠️ | 使用 `print()`，非 logging 模块；最后一行的 ✓ 字符在 GBK 终端崩溃 |
| 子查询性能 | ⚠️ | Q4 的 `sql2` 使用相关子查询，50支股票下可以接受 |
| 类型标注 | ⚠️ | 无类型提示（可接受级别） |

### 4. 运行结果

- ✅ 所有5项查询成功执行
- ✅ 报告文件已生成：`reports/survey/supplenment_survey_20260529.md`
- ❌ **脚本退出码非0**：最后一行 `print(f"\n[✓] 全部完成。")` 中 `\u2713`（✓）在 Windows GBK 终端无法编码，引发 `UnicodeEncodeError`

---

## 发现问题列表

### 🔴 Bug #01: UnicodeEncodeError（严重性：中等）

- **位置**: `main()` 第487行附近
- **问题**: `\u2713`（✓）在 GBK 编码的 Windows 控制台无法打印
- **影响**: 报告已成功写入磁盘，但脚本最终退出码为1，可能导致 CI/CD 误判失败
- **修复**: 替换为 `[OK]` 或 `[V]` 等 ASCII 安全字符

### 🟡 Warning #02: 无 try-finally 保护数据库连接（严重性：低）

- **问题**: `main()` 中连接在 `get_conn()` 中获取，`close()` 在 `main()` 末尾，中间无 try-finally
- **风险**: 如果某个查询抛异常，连接将不会被关闭，到主存耗尽或连接数上限才会释放
- **修复**: 使用 `with sqlite3.connect(DB_PATH) as conn:` 模式，或 try-finally 包裹

### 🟡 Warning #03: 停牌定义可能偏窄（严重性：低）

- **问题**: Q4 仅用 `close IS NULL` 判断停牌
- **风险**: 如果用 `close=0` 或 `pre_close=0` 标记停牌，则此类停牌不会被统计
- **建议**: 参考 Q2 的活跃标准 `close IS NOT NULL AND volume>0`，Q4 可增加条件 `OR volume=0`

### ⚪ Note #04: 文件名拼写错误

- **问题**: `supplenment_survey.py`→ 应为 `supplement_survey.py`（缺少字母 e）
- **影响**: 不影响运行，但文件索引和团队沟通易混淆

---

## 复现说明

脚本在 Windows (GBK终端) 上运行时：
1. 报告成功生成到 `reports/survey/`
2. 最后 `print()` 因 ✓ 字符崩溃
3. 报告内容完整，所有查询输出正确

---

## 审查建议

1. **必须修复** 🔴：将 `\u2713` 替换为 ASCII 安全字符
2. **建议修复** 🟡：添加 try-finally 或 with statement 保护数据库连接
3. **建议修复** 🟡：Q4 停牌判断条件增加 `volume=0` 或综合判定
4. **建议修复** ⚪：修正文件名拼写

---

*审查完成日期: 2026-05-29*
