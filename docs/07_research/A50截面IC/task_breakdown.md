# A50截面IC管线 - 编码拆分清单

**项目**：A50全成分股截面IC数据补证
**阶段**：编码（今晚前5项）
**依据设计**：design_v2.md
**编码流程**：coding_process_v1.1（拆分→编码→自检→墨萱审查→测试）

## 任务清单（今晚5项）

### task_01：supplement_survey.py — 补充摸底

| 项目 | 说明 |
|:----|:-----|
| **内容** | 独立脚本，跑5项SQL摸底（pe/pb/float_share缺失率、min_stocks截面覆盖率、复权方向实盘验证、停牌日分布），输出markdown报告 |
| **类型** | 工具脚本 |
| **预估工时** | 编码≤10min，测试+自检≤15min |
| **依赖** | 无（直接查market_data.db） |

### task_02：create_tables.py — DDL建表脚本

| 项目 | 说明 |
|:----|:-----|
| **内容** | 创建独立a50_ic.db，执行3张表DDL（a50_daily_ohlcv / a50_cross_ic_result / a50_universe），含PRAGMA foreign_keys=ON |
| **类型** | 数据层 |
| **预估工时** | 编码≤10min，测试≤15min |
| **依赖** | task_01产出摸底结论（影响DDL设计决策，如pe/pb字段NULL语义） |

### task_03：etl_a50_daily.py P1 — 数据提取 + 后复权

| 项目 | 说明 |
|:----|:-----|
| **内容** | 从stock_daily提取上证50数据写入a50_daily_ohlcv；后复权价格计算（含复权方向自动判定断言） |
| **类型** | ETL |
| **预估工时** | 编码≤10min，测试≤15min |
| **依赖** | task_02（表已创建）、task_01 Q3复权方向判定 |

### task_04：etl_a50_daily.py P2 — 停牌识别 + IPO处理

| 项目 | 说明 |
|:----|:-----|
| **内容** | 停牌日close置NULL（排除停牌占比>50%逻辑）、IPO首日双重判断（is_first_row + adj_prev_isna） |
| **类型** | ETL |
| **预估工时** | 编码≤10min，测试≤15min |
| **依赖** | task_03（数据已写入） |

### task_05：etl_a50_daily.py P3 — a50_universe构建

| 项目 | 说明 |
|:----|:-----|
| **内容** | 构建成分股列表表（a50_universe），优先tushare API → Wind/Choice → 手动CSV降级 |
| **类型** | ETL |
| **预估工时** | 编码≤12min，测试≤15min |
| **依赖** | task_02（表已创建） |

## 执行顺序

```
task_01 survey ──→ task_02 DDL ──→ task_03 ETL-P1 ──→ task_04 ETL-P2 ──→ task_05 ETL-P3
                                                                                 ↓
                                                                          等待Owner确认
```

## 编码流程（每子任务）

```
① 墨衡编码 → ② 墨衡自检(检查单) → ③ 墨萱审查(PASS/退回) → ④ 下一子任务
```

自检检查单（每任务通用）：
- [ ] 代码能运行（无语法错误）
- [ ] 注释完整（函数docstring + 关键逻辑）
- [ ] 数据库路径正确
- [ ] PRAGMA foreign_keys=ON（涉及数据库写入时）
- [ ] 异常处理（try/finally 关闭数据库连接）
