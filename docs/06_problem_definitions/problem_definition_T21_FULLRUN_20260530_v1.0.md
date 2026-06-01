---
author: 墨涵
created_time: 2026-05-31T09:25+08:00
closed_time: 2026-05-31T11:54+08:00
type: problem_definition_v1.0
problem_id: T21_FULLRUN_20260530
pipeline_stage: 5
status: CLOSED
closing_decision: "全票通过关闭T21。U1根因已闭环(OOM Killer)，T21_FIX已应用。U2转为独立改进项，待Owner排期。"
---

# 问题定义 v1.0 — T21_FULLRUN_20260530

## 核心现象（一句话）

T+21全量运行期间管线两次SIGKILL、黄金基线FAIL、估值因子全NULL，三项问题叠加。

---

## 严重性评估

**评级**：Critical

**依据**：
- SIGKILL导致管线不可持续运行 → Critical（工程基建问题）
- 黄金基线FAIL直接影响T+21是否可签署 → Critical（产出质量）
- 估值因子全线100% NULL暴露数据源缺失无告警 → Critical（数据质量防线缺失）

**紧急性**：高 — 阻塞T+21签署和T+14/T+7需求确认后的下一步推进

---

## 时间线

| 时间点 | 事件 |
|:------|:-----|
| 14:34 | T+21启动，拆分5子任务（T21_001~005） |
| 15:03 | T21_003 质量因子验收测试完成（t21_acceptance 8截面） |
| 15:24 | T21_004 全量管线启动（marine-s） |
| ~16:43 | **marine-s SIGKILL**，输出222截面/4,293行 |
| 17:00~17:27 | 发现被杀，报告产出 |
| ~17:27 | 重跑全量管线（mellow-o） |
| ~17:42 | **mellow-o SIGKILL**，输出428截面/7,731行 |
| 17:42~18:12 | 用 `--no-run` 跳过管线直接出报告 |
| ~18:12 | 全量审计：610截面/10,359行（管线持续写入中） |
| ~19:55 | 管线停止写入：最终792行/789截面 |
| 19:55~20:00 | 墨衡跑三条事后补充查询 |
| ~22:08~22:15 | 批处理：后补写库1604行（10因子,233截面） |
| ~22:23 | 批处理：后补写momentum_20d 150行 |
| ~22:39 | 修复运行：t21_fix_v1 986行（修正系数） |
| ~20:00~20:37 | 三方独立RCA + 归档 |

---

## 确认事实（有查证依据）

### 问题组A：SIGKILL管线异常

| # | 事实 | 依据来源 |
|:-:|:-----|:--------|
| A1 | 管线两次被SIGKILL（marine-s 约16:43, mellow-o 约17:42）| 现象P2/P4，见证者确认 |
| A2 | 两次运行不并发 | 现象P8，见证者确认 |
| A3 | 被杀时刻内存快照不可获取（Windows+WSL2，无dmesg/无系统日志）| 查证L1/L3，现象P11 |
| A4 | 事后18:59内存1.76GB/15.6GB（距第一次被杀已>2h） | 现象P11，查询记录 |
| A5 | 管线在--no-run模式下仍持续写入数据（16:39~19:54）| 查证M1/M2，代码分析+SQL |
| A6 | db_background_batch无需运行（无待写入数据），管线因SIGKILL未完成cleanup | 现象P9 |

### 问题组B：黄金基线FAIL

| # | 事实 | 依据来源 |
|:-:|:-----|:--------|
| B1 | 18:12基线报告5项指标：mean_ic_abs通过✅，positive_ratio/ic_std/significant_ratio FAIL ❌ | 18:12基线报告 |
| B2 | 单独过滤v1管线ISO数据重算，结论仍为FAIL（mixed data不改变结论）| 查证MC2 |
| B3 | half_life矛盾：验证脚本[4,12] vs req_draft_v2 >12周 | 现象P19 |
| B4 | 18:12快照过滤器链完整：610唯1截面→431→415有效窗口 | 查证H2 |
| B5 | baseline_half_life=0.47周，两套标准均FAIL | 现象P20 |

### 问题组C：估值因子IC=NULL

| # | 事实 | 依据来源 |
|:-:|:-----|:--------|
| C1 | pe_ttm/pb/ps_ttm/pcf_ttm rank_ic 100% NULL（非0.0）| 查证M3，SQL统计 |
| C2 | 所有估值因子num_stocks=0（0只股票有有效因子值）| 查证M3，SQL统计 |
| C3 | 根因：数据源 stock_daily.pe/pb全NULL，ps_ttm/pcf_ttm列不存在 | 现象P27/P30 |
| C4 | 管线行为符合设计（_build_null_record方法存在但valuation_factor路径未经过它，实际是NaN→dropna→continue跳过，等效于NULL）| 查证M3，代码确认 |

---

## 回写修正（阶段1文档需更新）

| # | 原表述 | 修正后 | 依据 |
|:-:|:-------|:-------|:----|
| W1 | P25"798"时间点标注"~18:12" | "~19:55（最终静态库）" | 查证H1 |
| W2 | P22/P28"后台未关闭的验证脚本持续写入" | "管线(--no-run模式)持续写入其他因子IC结果" | 查证M1+M2 |
| W3 | "估值因子IC=0" | "估值因子IC=NULL（未计算，非计算为0）" | 查证M3 |

---

## 未确认项

| # | 待查内容 | 责任人 | 截止时间 |
|:-:|:---------|:------|:--------|
| U1 | marine-s与mellow-o被杀时刻实际内存快照 | 系统限制 | 待Owner判断是否补充监控 |
| U2 | marine-s与mellow-o各自精确写入行数 | 墨衡 | 需管线日志确认 |

---

## 范围边界

**在内**：
- T+21全量运行管线行为（SIGKILL/产出/基线）
- 估值因子数据源可用性
- source_version/crated_at 追溯能力
- golden_baseline判定逻辑
- dmesg/log数据可用性（不可用时标记为系统限制）

**在外**：
- T+14 IC管线架构设计本身
- 基础数据采集（akshare ETL）设计决策
- T+21之前的编码实现质量
- --no-run 模式的实现细节

**不确定**（提交Owner裁决或进一步补充）：
- 是否需要添加内存监控（WSL2）以防止再次SIGKILL
- half_life 矛盾（两套标准）的最终选择方案
- 数据源缺失无告警是否为系统设计问题需独立跟踪

---

## 知识审查（墨涵）

**审查结论**：当前无需激活新知识条目。

**理由**：
- T+21全量运行异常属于工程执行问题，非新发现的可复现市场规律/因子特征
- SIGKILL + 数据源缺失是两个已知问题类型的实例化，非新insight
- 基线FAIL的具体指标（positive_ratio=0.4867等）是T+21验收数据，可记录到T+21任务档案中但不属于可复用的知识

**建议**：如有需要可在KID维护中补充一条engineering_practice类知识：
- "全量运行管线建议先用--no-run模式做一次dry-run验证，再启动正式运行"
- confidence: low（仅一次经验）

---

## 归档

- 问题定义：`docs/06_problem_definitions/problem_definition_T21_FULLRUN_20260530_v1.0.md`
- 关联文档：各阶段产出（phenomenon/structure_review/chain_review/verification）
