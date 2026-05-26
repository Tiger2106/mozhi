# 墨枢研究型回测试验方案

> **author:** 墨衡 (deepseek-reasoner)
> **version:** v1.1
> **review_approved_by:** 墨涵(知识), 墨萱(技术), 玄知(架构)
> **created_time:** 2026-05-24T10:37:00+08:00
> 
> **试验编号：** EXP-{YYYY}-{因子简写}-{三位序号}
> 示例：`EXP-2026-VOLATR-001`
> 
> **设计人：** {墨衡 / 墨萱 / 玄知 / 研究员姓名}
> **设计日期：** YYYY-MM-DD
> **version_schema：** {对应 backtest_schema 版本，如 v2}
> **version_content：** {内容迭代次数，从 1 开始}
> **version_status：** 草案 / 评审中 / 准予执行 / 已归档
> **关联 signal_defined：** `signal_defined_{task_id}.json`（未生成前填 pending）

---

## 〇、R001 问题定义（执行前必须通过）

> 依据 R001 规则：任何任务启动前，必须先完成问题定义的团队共识。
> 本节由提案人填写，墨涵确认，写入任务文档后方可进入后续章节。

### 0.1 现状描述（数据/事实，不猜测）

*用可观测的数据描述当前状态。例如：l_vol_atr 在12只标的、1210个交易日的 IC/IR 检验中 IR=0.084，高于阈值 0.05，但正值比仅 51.57%，低于预期的 55%。*

| 项目            | 内容                    |
| ------------- | --------------------- |
| 标的            |                       |
| 时间段           |                       |
| 关键数据          |                       |
| 数据来源          | market_data.db（唯一权威源） |
| 复权方式          | qfq 前复权（强制）           |
| adj_base_date | 初步设定，最终见 §2.2 数据窗口表    |

> **注意：** adj_base_date 的最终值在 §2.2 数据窗口表中确定，§0.1 仅作初步标记。

### 0.2 不解决的后果 + 紧急性

*描述不做这个试验的机会成本或风险。要求附带量化估算，避免空泛套话。*

**填写指引（示例）：**
> *"若 l_vol_atr 的信号噪声问题未解决，后续依赖该因子的组合策略将继续在震荡行情中产生亏损，预计每次震荡周期的回撤幅度 3-5%，按历史震荡频率（年均 4-5 次）累计损失 12-25% 的 alpha。"*

### 0.3 根因分析（至少追到第三层）

> 每层必须能回答"为什么上一层会发生"，否则不算合格。
> **例外条款：** 若执行人认为第三层不存在（即第二层已经是系统性/不可归因的上限），须在根因分析末尾注明"已追至可解释极限"，由团队讨论确认。
> **QA 触发：** 若后续 QA 发现第三层可以更深入但执行人未追，记为质量问题。

- **第一层（直接原因）：**
- **第二层（间接原因）：**
- **第三层（系统性原因）：**

### 0.4 问题陈述（一句话）

> 格式：**谁** 在 **什么场景** 下，因为 **什么**，导致 **什么后果（含可观测指标）**。
> 示例：墨枢在震荡行情下，因 l_vol_atr 缺少市场状态过滤，导致信号噪声过高（IC 正值比 <52%，IR 衰减至 0.03）。

**填空模板：**
> **问题陈述：** [执行人/系统] 在 [市场状态/场景] 下，因 [根因核心]，导致 [可观测后果]，具体表现为 [指标] [数值] [阈值对比]。

### 0.5 通过条件核查

| 条件          | 负责人  | 状态  | 验收人签字/日期    |
| ----------- | ---- | --- | -------------- |
| 现状有数据支撑     | 提案人  | ☐   |                |
| 影响范围和紧急性已评估 | 提案人  | ☐   |                |
| 根因至少到第三层    | 团队讨论 | ☐   |                |
| 问题陈述全员认可    | 墨涵确认 | ☐   |                |
| 写入任务文档      | 墨涵   | ☐   |                |

**退回/仲裁流程：**
- 以上任一环节发现不合格 → 退回起草人修改
- 退回最多 2 次，第 3 次仍不合格 → 提交 Owner 裁决
- 裁决结论为"通过"或"终止试验"，不可再退回

---

## 一、试验背景与核心假设

### 1.1 背景

*简述本试验的来源：是 IC/IR 报告中发现的优质因子待深入验证，还是数据修复后的重新检验，还是新因子的首次测试。*

### 1.2 核心假设（可证伪）

- **H0（原假设）：** 在 {市场状态} 下，{新因子/修改} 相比基准，不能提升 {指标}。
- **H1（备择假设）：** 在 {市场状态} 下，{新因子/修改} 能提升 {指标}，且在样本外保持稳定。

### 1.3 因子体系归属

> 对应三层量能体系，明确本试验因子属于哪一层。
> **注意：** 因子名必须已存在于 `methods.db` 的因子注册表中，否则回测引擎将拒绝执行。

| 因子名 | 层级                        | 说明  |
| --- | ------------------------- | --- |
|     | L1 绝对量 / L2 相对化量 / L3 结构量 |     |

---

## 二、数据与标的定义

### 2.1 标的池（Universe）

| 项目                     | 内容                    |
| ---------------------- | --------------------- |
| 标的列表                   |                       |
| 排除标准                   | 停牌率 >20%、ST 股票、**上市未满2年** |
| free_float 口径          | 东财口径（系统唯一标准口径）        |
| free_float_source 字段值  | eastmoney             |
| **free_float 下限**      | **≥ 0.5**（若低于此值需说明替代规则） |
| **复权质量校验**             | **adj_factor 异常跳变检验（详见 2.3）** |

*变更说明：上市未满1年 → 2年（v1.0）；新增 free_float ≥ 0.5、复权质量校验。*

### 2.2 数据窗口

| 阶段                 | 开始  | 结束  | adj_base_date | 说明                   |
| ------------------ | --- | --- | :----------: | -------------------- |
| 暖机期（Warm-up）       |     |     |              | 至少为最长指标窗口的 2 倍，不参与回测 |
| 样本内（In-Sample）     |     |     |              | 用于参数扫描               |
| 样本外（Out-of-Sample） |     |     |              | 盲测，锁定参数后运行           |

**停复牌运行时处理规则：**
1. **持有期遇停牌**：停牌期间信号保留，复牌后首个交易日以复牌价执行买入/卖出
2. **复牌价格处理**：以复牌当日开盘价执行（如涨停/跌停则延迟至可交易）
3. **长期停牌标记**：停牌超过 20 个交易日 → 标记为异常停牌（`exception_suspension = 1`），排除因子计算
4. **信号边界敏感说明**：复牌首日的跳空缺口可能影响因子值，需在试验报告中注明

**暖机期受限标记：**
- 若标的上市日期晚于暖机期开始日期 → 该标的标注"暖机期受限（`warmup_limited = true`）"
- 受限标的在回测报告中单独列示其起始时间

*变更说明：新增 adj_base_date 列（从 §0.1 移至 §2.2，P0-3 of 墨衡§0评审）；新增停复牌处理规则（P1-9）；新增暖机期受限标记（P2-18）。*

### 2.3 数据质量前置检查

> 此项为硬性要求，任何时间片跑回测前必须通过。
> **注：** 本检查脚本已独立化为 `C:\Users\17699\mozhi_platform\scripts\qc\data_qc_check.py`，版本锁定引用。禁止使用 assert 替代脚本执行。

```python
# 必须在回测启动前执行，结果写入 validation_check 表
# check_name 命名规范：data_qc_{ts_code}_{start}_{end}
# 使用预置脚本：python data_qc_check.py --ts_code {ts_code} --start {start} --end {end}

# === 预置脚本 data_qc_check.py 核心逻辑（供参考，非执行入口）===
import sys
def run_data_qc(ts_code, start, end):
    df = data_source.fetch_daily(ts_code, adjust="qfq")
    bh = df['close'].iloc[-1] / df['close'].iloc[0] - 1
    
    # 硬阻断：adj_factor NULL 检查
    if df['adj_factor'].isna().any():
        raise RuntimeError(f"adj_factor 含 NULL 值，ts_code={ts_code}，数据未复权")
    
    # 硬阻断：复权因子异常跳变检查
    adj_jumps = df['adj_factor'].pct_change().abs()
    if (adj_jumps > 0.5).any():
        raise RuntimeError(f"adj_factor 出现 >50% 跳变，ts_code={ts_code}，可能存在数据异常")
    
    # 写入 validation_check
    insert_validation_check(
        check_name=f"data_qc_{ts_code}_{start}_{end}",
        result="pass",
        detail=f"Buy&Hold验证：{bh:.2%}，adj_factor NULL：无，adj_factor异常跳变：无"
    )
    print(f"data_qc passed: {ts_code} B&H={bh:.2%}")
    
if __name__ == "__main__":
    # 实际使用时调用本脚本，不可直接复用此代码块
    run_data_qc(sys.argv[1], sys.argv[2], sys.argv[3])
```

> **验收规则：** 脚本输出的 validation_check 记录必须存在于 `backtest_run` 关联的 `validation_check` 表中。
> 禁止在回测脚本内使用 `assert` 替代该独立脚本。

*变更说明：assert 改为 raise 硬阻断，脚本独立化锁版本（P1-10）。*

---

## 三、因子配置与控制变量

### 3.1 因子参数

```json
{
  "factor_name": "",
  "factor_version": "",
  "data_source": "market_data.db",
  "adj_method": "qfq",
  "adj_base_date": "<从 §2.2 数据窗口表继承>",
  "params": {}
}
```

### 3.2 变量矩阵

**控制变量（保持恒定，不参与扫描）：**

| 变量    | 值                                      |
| ----- | -------------------------------------- |
| 手续费率  | 双边 0.03%                               |
| 滑点率   | 0.1%（Layer Q 审计将对 0.1%/0.3%/0.5% 三档进行灵敏度审计） |
| 仓位方式  | equal / volatility / factor_weight（选一） |
| 最大持仓数 |                                        |
| 初始资金  |                                        |

**自变量（参数扫描空间）：**

| 参数名 | 扫描范围 | 步长  |
| --- | ---- | --- |
|     |      |     |

### 3.3 A 股硬约束（Execution 层必须执行）

| 约束   | 规则                   | 异常处理        |
| ---- | -------------------- | ----------- |
| T+1  | 当日买入次日方可卖出           | 反向信号延迟至次日开盘 |
| 涨跌停  | 涨停不可买入（未封死除外），跌停不可卖出 | 信号保留至次日重新判断 |
| 成交时间 | 信号触发限制在 09:35–14:55  | 规避集合竞价和尾盘异常 |
| 冲击成本 | 单笔成交量 ≤ 当日成交量的 {X}%  | 超限则分批或放弃    |

**成交时间约束验收规则：**
- `trade_log` 中每条记录须包含 `exec_time` 字段
- 验收人独立抽检 ≥ 5% 的交易记录，确认 `exec_time` 落在 09:35–14:55
- 抽检发现违规 → 退回执行人修复

*变更说明：滑点率增加三档灵敏度审计说明（P2-19）；成交时间增加验收规则（P1-11）。*

---

## 四、IC/IR 验收标准

> 本系统 Universe 为小规模标的池（< 50只），有效因子阈值与大 Universe 不同。

### 4.1 单因子有效性门槛

| 指标                | 最低门槛             | 优秀门槛             | 说明                          |
| ----------------- | ---------------- | ---------------- | --------------------------- |
| IR                | > 0.05           | > 0.08           | 小 Universe 适用阈值              |
| Mean IC           | > 0              | > 0.02           |                             |
| **IC 正值比**       | **> 50%**        | **> 53%**        | v1.1 改回 >50% 为强制线（详见下方边界规定）|
| **IC 正值比边界规定** | **50% < IC 正值比 ≤ 53%** | 处于该区间时须附加<b>单调性证据</b>：L3 > L2 > L1（单调）且 L3-L1 spread > 0；无单调性时不通过 |
| 检验天数              | ≥ 200            | ≥ 500            |                             |
| 分层 IR（L3-L1）      | > 0.02           | > 0.05           | 多空组合稳定性                     |
| **分层单调性辅助判断**   | **L3 > L2 > L1（单调）** |                  | **未达 IR 门槛时的补充判断通道**       |

**Universe < 12 只的专属规则：**
- IR 门槛维持 > 0.05，但等效检验天数 ≥ 1,000（标的×交易日乘积）
- 分层单调性作为**主要判断依据**（替代 IR 的统计显著性）
- 报告中标明 `small_universe = true`

**Override 机制：**
- IR 在 [0.04, 0.05) 区间，但分层单调性良好（L3 > L2 > L1 且 spread > 0.02）
- 可标记为"低置信通过（`low_confidence_pass = true`）"状态
- 需双倍样本外倍验（OOS 时间窗口翻倍）
- 在 `validation_check` 中记录 `override_by` 字段

*变更说明：IC 正值比维持 >50% 为强制线，>53% 为优秀线；50%~53% 区间需附加单调性证据；增加 Universe < 12 专属规则；增加分层单调性辅助判断 + override 机制。*

### 4.2 策略组合验收门槛（Layer Q）

| 指标             | 门槛              | 说明               |
| -------------- | --------------- | ---------------- |
| 总交易次数（IS+OOS）  | ≥ 30 次          | 不达标直接熔断，归档"低显著性" |
| 夏普比率           | ≥ 1.2           |                  |
| 最大回撤           | ≤ 15%           |                  |
| 参数邻域收益劣化       | ≤ 20%           | 过拟合审计，防止孤峰       |
| 胜率             | ≥ 45%           |                  |
| 盈亏比            | ≥ 1.8 : 1       |                  |
| 样本外一致性         | OOS 曲线斜率与 IS 一致 | P-value < 0.05   |

**参数邻域劣化计算方法：**
- **计算公式（口径A 优先）：** `劣化率 = (最优收益 - 邻域平均收益) / 最优收益`
- **邻域定义：** 单参数时 ±1 步；多参数时曼哈顿距离 ≤ 1 的网格点
- **统计报告要求：** 除均值外需同时报告邻域最差点比值（`max_deterioration`），确保无孤脚

**Layer Q 等级映射表：**

| 等级 | 条件 | 后续处理 |
|:---:|:----|:--------|
| A | 所有指标通过 + OOS 斜率显著（p<0.01） | 晋级实盘备选 |
| B | 所有指标通过 | 晋级组合配置池 |
| C | ≥4 项指标通过，或 A 级指标全部达标但有 1 项边界值 | **条件归档（`high_risk` 标记）+ 需 Owner 额外审批** |
| D | <4 项指标通过，或 P2 自洽性失败 | **阻断归档**：数据层问题→修复后重跑（返 Step2）；因子本身问题→H0 失败归档 |

**Layer Q 评级归属：**

| 角色 | 职责 | 名称 |
|------|------|------|
| 规则制定 | 定义评级维度、评分公式、阈值条件 | 墨涵 |
| 算法实现 | 将规则编码为可执行审计模块 | 墨衡 |
| 阈值批准 | 批准最终阈值，记录变更日志 | Owner |
| 评级准确性核验 | **抽查：每轮抽选 ≥ 1 个 B 级以上策略，手动复核置信度评分** | 墨萱 |

**复核触发条件（验收人有权启动人工复核）：**
验收人发现以下任一情况时，有权启动人工复核，不自动进入 Layer Q 审计：
1. 某指标恰好在门槛 ±3% 的边界区间内（如 IR=0.052 或 夏普=1.21）
2. 时间切片分析发现收益集中在单一子窗口（单月贡献 >50% 总收益）
3. 标的覆盖率（通过 IC 检验的标的数 / 总标的数）< 60%
4. 标的池的实际有效标的数 < 10 只（小样本风险）

人工复核结论：通过 / 需补充数据 / 退回重跑。复核结论由验收人写入 `validation_check`，`check_name='layer_q_review'`。

*变更说明：新增等级映射表、评级归属表、复核触发条件（P0-4）；补充参数邻域劣化计算方法（P0-4 墨衡评审建议）。*

### 4.3 价格与因子数据精度要求

| 检验项                    | 阈值                                          | check_name                   |
| ---------------------- | ------------------------------------------- | ---------------------------- |
| 复权价格误差（RMSE）          | < 0.1%                                      | price_rmse_{ts_code}         |
| 因子值 Pearson 相关系数       | **> 0.999（四舍五入至 4 位小数）**                      | factor_pearson_{factor_name} |
| **P2 自洽性（精确版本）**    | **因子值 Pearson r ≥ 0.999 且 max(|diff_per_day|) < 1e-8** | p2_self_consistency          |
|                     | **核心绩效指标差异 ≤ 0.1%（夏普/IR/总收益）**                |                              |
|                     | **随机种子已固定并记录 seed 值**                          |                              |

**P2 自洽性判定细则：**
1. **因子值一致性：** 两次独立计算得到的因子值序列 Pearson r ≥ 0.999（四舍五入到 4 位小数），且 max(|diff_per_day|) < 1e-8
2. **工程可接受差异：** 如果差异仅存在于浮点最后 2 位（< 1e-10），视为工程可接受，验收人不介入
3. **判定场景规则：**
   - 计算结果 r=0.9990 → 不通过，需排查代码路径
   - 计算结果 r=0.99915 → 通过（四舍五入到 4 位为 0.9992，> 0.999）
   - 两次因子值完全相同但 r=NaN → 检查是否有常数序列（方差为 0 时 r 未定义）
4. **验收环境锁定：** 以模板中锁定的计算环境（Python 3.11 + NumPy 1.26）为准。跨环境复现产生的差异不纳入人工容差范围
5. **随机种子：** `random_seed` 必须固定并记录到试验方案中

*变更说明：P2 自洽性修改为精确版本（P1-12）。*

---

## 五、试验流程

```
Step 1  知识库自查
        ↓ 检索 knowledge.db，查找相同因子/标的的历史失败案例
        ↓ 重点关注：过拟合记录、数据污染记录、信号边界问题
        ↓ 输入：factor_name, universe list
        ↓ 输出：匹配的历史失败案例（数量+原因分类）
        ↓
        ════ 数据传递契约 ════
        Step 1 完成后自动写入中间数据文件：
        `signals/tasks/EXP-{ID}_knowledge_check.json`
        结构：{"query_status": "SUCCESS/ERROR/TIMEOUT",
              "matched_count": 0,
              "cases": [{"exp_id": "...", "failure_reason": "..."}],
              "blocker": false}
        Step 2 启动前检查该文件：
        - blocker=true → 流程建议中止，需 force_override 方可继续
        - 查询失败(ERROR/TIMEOUT) → 不阻断流程，但在 validation_check 标注 knowledge_query_error
        - 冷启动（knowledge.db 为空）：knowledge_check.json 写入 {"found": false, "note": "cold_start"}，不阻塞流程

Step 2  代码冻结 + 自洽性验证
        ↓ 冻结代码版本
        ↓ ──── 自动注入机制 ────
        │  执行引擎在 Step4/Step5 启动时自动读取当前 HEAD git hash
        │  并写入 backtest_run.version_tag（不依赖人工输入）
        │  验收人核对：backtest_run.version_tag == 冻结版本号
        ├─── 如环境不支持自动注入 ───
        │  执行人记录 version_tag（git commit hash），
        │  验收人可执行 git log --oneline HEAD 核对
        ├───────────────────────
        ↓ 同向量跑两次，确认 P2 自洽性通过后再继续
        ↓ 写入 validation_check（check_type='self_consistency'）

   [版本变更记录，如需人工回退重跑：]
   ┌─────┬──────────┬──────────┬──────────┬──────┐
   │版本  │ 前次hash │ 修改后hash│ 修改原因  │ 批准人│
   ├─────┼──────────┼──────────┼──────────┼──────┤
   │ v1  │   —      │ abc123   │ 初始冻结  │ 墨涵 │
   │ v2  │ abc123   │ def456   │ 修复参数  │ 墨涵 │
   └─────┴──────────┴──────────┴──────────┴──────┘
   │  验收人核对标准：backtest_run.version_tag == 最后一次执行的 HEAD

Step 3  数据质量检查
        ↓ 执行 2.3 节预置脚本（data_qc_check.py，独立可执行文件，非内联 assert）
        ↓ 通过后写入 validation_check（check_type='data_quality'）

Step 4  样本内参数扫描
        ↓ 多参数矩阵扫描，绘制参数热力图
        ↓ 选"高原中心"参数，拒绝孤峰
        ↓ 参数扫描结果写入 params_snapshot 表（新增步骤）
        ↓ 禁止从 Step4 中间结果直接传递数据至 Step5

Step 5  因子 IC/IR 检验
        ↓ params_snapshot → 读取锁定参数 → 单独跑 IC/IR
        ↓ 生成 IC 时序、累计 IC、分层回测
        ↓ 结果写入 factor_result 表

   ╔══════════════════════════════════════╗
   ║ 自动熔断判定                          ║
   ║   IR ≤ 0 且 IC 正值比 ≤ 45%          ║
   ║   → 自动判定为 D 级                   ║
   ║   → Step6 仅作分析归档（不晋级）       ║
   ╚══════════════════════════════════════╝

Step 6  样本外盲测
        ↓ 锁定参数，在 OOS 数据集运行
        ↓ 结果写入 performance_summary + trade_log

Step 7  Layer Q 审计
        ↓ 自动计算第四节所有指标
        ↓ 出具审计报告，评级 A / B / C / D
        ↓ 不达标因子写入 validation_check（result='fail'）
        ↓
        ↓          ┌──── Layer Q 评级判定 ────┐
        ↓          │                           │
        ↓      ┌───┼───┬───┬───┐              │
        ↓      │   │   │   │   │              │
        ↓      ▼   ▼   ▼   ▼   │              │
        ↓      A   B   C   D   │              │
        ↓      │   │   │   │   │              │
        ↓      │   │   │   └───┼────▶ 阻断    │
        ↓      │   │   │       │       ├── 数据层问题→退回 Step2 修复重跑
        ↓      │   │   │       │       └── 因子本身问题→进入 §7.1 H0 失败归档
        ↓      │   │   │       │
        ↓      │   │   └───────┼────▶ 条件归档
        ↓      │   │               signal_defined 添加 "high_risk" 标记
        ↓      │   │               需 Owner 额外审批
        ↓      │   │
        ↓      └───┘
        ↓          │
        ↓          ▼
        ↓   Step 8  signal_defined 归档

Step 8  signal_defined 归档
        ↓ 通过审计后生成 signal_defined_{task_id}.json
        ↓ 触发下游流水线
        ↓
        ════ 生成角色说明 ════
        主路径（自动）：backtest runner 在 Layer Q 评级为 A/B 时自动触发生成
        回退路径（人工）：如 runner 未自动生成（环境异常/故障），由 墨衡 手动执行
                        `python scripts/layer_q/generate_signal_defined.py --exp_id EXP-{ID}`
        Layer Q 评级为 C/D 时禁止生成 signal_defined，改为写入
        `signals/signals/signal_defined_{task_id}.failed.json`
        内容：{"status": "REJECTED", "layer_q_rating": "C/D", "reason": "<审计未通过原因>"}
```

**参数传递规范（Step4 → Step5）：**
- Step4 参数扫描结果全部写入 `params_snapshot` 表
- Step5 从 `params_snapshot` 读取锁定参数后**单独执行完整的因子计算路径**，生成 IC/IR 结果
- 严禁直接复用 Step4 的中间计算结果（因子值、IC 值等）作为 Step5 的 IC/IR 输入，以防止参数挖掘的数据泄露
- `params_snapshot` 表记录包括：参数组合、收益矩阵、热力图数据、选定参数的理由

*变更说明：Step2 增加自动注入机制（P0-5）；Step4→5 参数传递规范（P0-8）；Step5→6 自动熔断（P1-13）；Step7→8 分支流程（P0-6）。*

---

## 六、数据库写入规范

### 6.1 backtest_run 入口记录

```sql
INSERT INTO backtest_run (id, run_name, version_tag, triggered_by, periods, notes)
VALUES (
    '{uuid}',
    'EXP-2026-{FACTOR}-{SEQ}_{ts_code}',
    '{git_commit_hash}',
    '{设计人}',
    '[{"label":"{period_label}","start":"{YYYYMMDD}","end":"{YYYYMMDD}","trading_days":{N}}]',
    '{简要描述}'
);
```

**trading_days 填充规范：**
- **必须调用系统日历接口自动计算**，禁止手工填写
- 接口函数：`get_trading_days(start, end, exchange='SSE')`，统一使用 A 股交易日历口径
- `trading_days` 锁定为 Universe 公共交易日：取所有标的的共同可交易日的并集，排除周末、A 股假期、全市场停牌日
- 附录 B 检查清单中增加对应项：`trading_days 为系统自动填充（非手工）`

*变更说明：新增自动填充规范（P1-14）。*

### 6.2 validation_check 命名规范

| check_name 前缀                  | 适用场景         |
| ------------------------------ | ------------ |
| `p2_self_consistency_{factor}` | P2 自洽性检验     |
| `data_qc_{ts_code}_{start}`    | 数据质量前置检查     |
| `price_rmse_{ts_code}`         | 复权价格误差检验     |
| `factor_pearson_{factor}`      | 因子值一致性检验     |
| `adj_factor_{ts_code}`         | 复权因子 NULL 检验 |
| `layer_q_{exp_id}`             | Layer Q 综合审计 |

**命名规范验收标准：**

```python
# 硬约束（违反即 FAIL，必须修复）
R1 = "只允许小写字母(a-z)、数字(0-9)、下划线(_)"
R2 = "日期统一使用 YYYYMMDD 格式，不使用分隔符"
R3 = "因子名使用 §1.3 因子体系归属表中的规范名称"

# 宽容规则（WARN 级别，记录但不阻断验收）
W1 = "交易所前缀（sh/sz/SS/SZ）可省略"           # 例如 600000 vs sh600000
W2 = "下划线顺序变化但含义不变的可接受"              # 例如 price_rmse_000001_2026 vs price_rmse_2026_000001
W3 = "完整的因子全名替换为注册的规范简写"             # 例如 factor_pearson_l_vol_atr

# 验收判定优先级
1. 违反 R1/R2/R3 → FAIL，退回修改
2. 仅落入 W1/W2/W3 范围 → WARN，自动修复后通过
3. 完全一致 → PASS
```

*变更说明：新增 R1/R2/R3 硬约束 + W1/W2/W3 宽容规则（P1-15）。*

### 6.3 废弃结果标记

> **推荐使用预置脚本** `mark_abandoned.py`（路径：`C:\Users\17699\mozhi_platform\scripts\utils\mark_abandoned.py`）执行废弃标记，禁止手写 SQL。
> 
> 使用方式：
> ```bash
> python mark_abandoned.py --run_id <uuid> --reason "数据污染：{具体描述}" [--restart]
> ```

**新增字段（validation_check 表）：**

```sql
-- 需 DBA 确认表结构修改后执行
ALTER TABLE validation_check ADD COLUMN `is_deprecated` INTEGER DEFAULT 0;
ALTER TABLE validation_check ADD COLUMN `deprecated_at` TEXT;
ALTER TABLE validation_check ADD COLUMN `deprecated_by` TEXT;
ALTER TABLE validation_check ADD COLUMN `deprecated_reason` TEXT;
ALTER TABLE validation_check ADD COLUMN `redo_run_id` TEXT;  -- 关联重跑后的 run_id
```

**标记废弃时（不修改原始 result）：**

```sql
UPDATE validation_check
SET is_deprecated = 1,
    deprecated_at = strftime('%Y-%m-%dT%H:%M:%S+08:00', 'now'),
    deprecated_by = '{执行人}',
    deprecated_reason = '数据污染：{具体描述}',
    redo_run_id = '{新的 run_id（如有）}'
WHERE run_id = '{原 run_id}' AND check_name = '{check_name}';
```

**验收人核查手段：**

```sql
-- 查询所有被废弃的记录
SELECT * FROM validation_check
WHERE is_deprecated = 1 AND deprecated_at IS NOT NULL;

-- 对比原始结果和废弃信息
SELECT run_id, check_name, result, is_deprecated, deprecated_by, deprecated_reason
FROM validation_check
WHERE run_id LIKE 'EXP-{ID}%';
```

**验收清单新增项：**
- [ ] 检查 `is_deprecated = 1` 的记录，确认废弃原因已记录且有执行人签名
- [ ] 确认废弃操作的 `deprecated_at` 时间戳与数据污染发现日志一致
- [ ] 确认废弃的 run_id 与重跑的 run_id 通过 `redo_run_id` 建立了关联

*变更说明：新增预置脚本 + 废弃标记扩展字段 + 验收核查清单（P1-20）。*

---

## 七、试验结论与知识沉淀

### 7.1 试验结论

- [ ] **H1 成立（试验成功）：** 通过 Layer Q 审计，晋级实盘备选 / 组合配置池
- [ ] **H0 成立（试验失败）：** 未通过审计，归档失败案例库

**Layer Q 评级与结论联动规则：**

| Layer Q 评级 | §7.1 结论 | §7.3 写入范围 |
|:---------:|:--------:|:----------:|
| A / B | H1 成立（试验成功） | factor_repository.db + knowledge.db + 报告目录 |
| C | 有条件 H1 成立（标注 `high_risk`） | 同上 + 额外 Owner 审批记录 |
| D | H0 成立（试验失败） | 仅 knowledge.db + 报告目录（不更新 factor_repository.db） |

**Layer Q 最终评级：** A / B / C / D

| 指标      | 实测值 | 门槛     | 通过  |
| ------- | --- | ------ | --- |
| IR（IS）  |     | > 0.05 | ☐   |
| IR（OOS） |     | > 0.05 | ☐   |
| 夏普比率    |     | ≥ 1.2  | ☐   |
| 最大回撤    |     | ≤ 15%  | ☐   |
| 总交易次数   |     | ≥ 30   | ☐   |
| 参数邻域劣化  |     | ≤ 20%  | ☐   |
| P2 自洽性  |     | 一致     | ☐   |

### 7.2 失败根因归因（试验失败时必填）

> 作为系统的负向样本，防止重复踩坑。
> **每个被勾选的选项必须附带至少一条数据证据。** 缺少证据 → WARN，验收退回。

**格式示例：**
```
[x] 参数孤峰 — 证据：(params=10,50)收益15%，(15,50)收益-3%，(10,55)收益-1%
[ ] 时代依赖 —
[x] 数据层问题 — 证据：002230在adj_base_date=20230101前后adj_factor跳变2.3倍
```

- [ ] **参数孤峰：** 最优参数左右偏移一格，收益崩塌
- [ ] **时代依赖：** 策略依赖单边牛市行情，震荡熊市亏损
- [ ] **摩擦成本吞噬：** 信号频率过高，手续费超过毛利润
- [ ] **数据层问题：** 复权口径不统一 / adj_factor 缺失
- [ ] **信号边界敏感：** 排序/缺口处理差异导致信号偏移
- [ ] **统计噪声：** IC 正值比接近 50%，无统计显著性
- [ ] **其他：** ___________________________________________

**验收规则：**
- 被勾选的选项如缺少数据证据（字段为空或明显无意义）→ **WARN**，要求补充
- "其他"选项被勾选但未填写具体内容 → **WARN**，要求填写
- 累计 2 个及以上 WARN → 验收不通过，退回

> **H0 成立 → 填写根因归因 → 执行脚本归档：**
> ```bash
> python C:\Users\17699\mozhi_platform\scripts\archive\archive_failure.py --exp_id EXP-...
> ```
> 脚本自动完成：
> 1. `knowledge.db` 插入结构化记录（factor_name, reason_category, detail, link_to_report）
> 2. 失败案例目录下生成 .md 报告（含 7.2 根因分析）
> 3. `backtest_run` 标记为 `ARCHIVED_FAILED`

### 7.3 知识库写入（试验完成后强制执行）

> **写入目标是两库 + 归档目录**（非三库，v1.0 修正）。

```
factor_repository.db   → 新增/更新方法节点：{factor_name} v{version}
                          关联市场状态：TREND_UP / OSCILLATION / PANIC
knowledge.db           → 归档本报告路径
归档目录                 → 报告目录：C:\Users\17699\mozhi_platform\reports\{exp_id}\
```

**写入失败门禁规则：**
- 写入失败（任一一库写入异常）→ 阻止 `signal_defined` 归档，禁止进入 Step8
- 执行人须排查写入失败原因并修复后重试

**验收人核查标准（验收时执行）：**

```sql
-- ① 确认 factor_repository.db 中方法节点已新增/更新
SELECT node_id, factor_name, version, updated_at
FROM factor_repository.nodes
WHERE factor_name = '{factor_name}' AND version = '{version}';
-- 预期：至少返回1行，updated_at 不早于试验执行时间

-- ② 确认 knowledge.db 中报告路径已归档
SELECT entry_id, title, archive_path, archived_at
FROM knowledge.entries
WHERE object = 'EXP-{ID}' OR title LIKE 'EXP-{ID}%';
-- 预期：返回1行，archive_path 指向实际存在的文件路径

-- ③ 确认 backtest_run 中该试验的全部 validation_check 记录
SELECT run_id, check_name, result, detail, is_deprecated
FROM validation_check
WHERE run_id LIKE 'EXP-{ID}%';
-- 预期：返回该试验的全部 validation_check 记录
```

**验收规则：**
- 三条 SQL 任一返回 0 行 → **FAIL**，退回补写
- `knowledge.db.entries.archive_path` 指向的文件不存在 → **FAIL**，退回
- 所有检查通过 → **PASS**，确认知识沉淀已发生

**附录 B 门禁条件新增项：**
- [ ] 验收人已执行两库+归档目录写入核查 SQL（三条全部确认通过）
- [ ] 未通过时，signal_defined 归档被门禁阻断（不得进入 Step8）

*变更说明："三库"修正为"两库+归档目录"（P2-21）；新增写入失败门禁规则（P0-7）；新增验收人核查 SQL（P0-7）。*

---

## 附录 A：文件清单

| 文件                 | 路径                                          | 说明      |
| ------------------ | ------------------------------------------- | ------- |
| 本方案                | `signals/tasks/EXP-{ID}_plan.md`            |         |
| 回测报告               | `signals/tasks/EXP-{ID}_report.md`          |         |
| 数据修复日志             | `signals/tasks/migration_{topic}_{date}.md` | 如有数据层变更 |
| signal_defined     | `signal_defined_{task_id}.json`             | 审计通过后生成 |
| **失败案例归档文件**（试验失败时） | `signals/tasks/EXP-{ID}_failure_analysis.md` | H0 归档时生成 |

*变更说明：新增失败案例归档文件路径。*

---

## 附录 B：快速填写检查清单

> 提交评审前，逐项确认。

**R001 问题定义：**

- [ ] 现状有数据支撑（非猜测）
- [ ] 根因追到第三层，或已标注"已追至可解释极限"
- [ ] 问题陈述包含"对象+偏差+可观测指标"
- [ ] 墨涵已确认写入任务文档

**数据层：**

- [ ] 数据源为 market_data.db（非 analysis.db）
- [ ] 复权方式为 qfq
- [ ] adj_factor 无 NULL
- [ ] adj_factor 无异常跳变（>50%）
- [ ] free_float 口径为东财
- [ ] free_float ≥ 0.5（或已说明替代规则）
- [ ] 标的上市已满 2 年（或标注"暖机期受限"）

**代码层：**

- [ ] version_tag 已记录（git commit hash），且与 `backtest_run.version_tag` 一致
- [ ] P2 自洽性已验证（r ≥ 0.999，|diff| < 1e-8）
- [ ] 随机种子已固定并记录
- [ ] 无硬编码 SQL 直接读 db 文件
- [ ] 使用预置脚本 `data_qc_check.py`（非内联 assert）

**回测层：**

- [ ] 暖机期已排除
- [ ] A 股硬约束已启用
- [ ] 样本内/样本外严格分离
- [ ] 停复牌处理规则已应用
- [ ] `trade_log` 中已包含 `exec_time` 字段
- [ ] `trading_days` 为系统日历自动填充（非手工填写）

**归档层：**

- [ ] validation_check 已全部写入
- [ ] 命名规范满足 R1/R2/R3 硬约束
- [ ] 失败结论有根因归因且附带数据证据
- [ ] 两库+归档目录已写入（`factor_repository.db` + `knowledge.db` + 报告目录）
- [ ] 验收人已执行两库写入核查 SQL（三条全部确认通过）
- [ ] 未通过时 signal_defined 被门禁阻断
- [ ] signal_defined 触发角色已确认（自动触发 / 人工回退路径）

---

## 附录 C：预置脚本清单

| 脚本路径                                                  | 用途                 | 调用时机              |
| ----------------------------------------------------- | ------------------ | ----------------- |
| `scripts/qc/data_qc_check.py`                         | 数据质量前置检查（替代 assert） | Step3             |
| `scripts/utils/mark_abandoned.py`                     | 废弃结果标记             | 发现数据污染时           |
| `scripts/archive/archive_failure.py`                  | 失败案例归档             | H0 成立时            |
| `scripts/utils/calc_period_trading_days.py`           | 计算区间交易日数           | Step5 数据库写入时      |
| `scripts/knowledge/search_failure_knowledge.py`       | 检索历史失败案例（knowledge.db） | Step1 知识库自查时      |
| `scripts/layer_q/run_layer_q_audit.py`                | Layer Q 审计模块       | Step7              |
| `scripts/writeback/finalize_exp.py`                   | 试验最终化：两库写入 + 状态标记   | 试验完成时（Step8 之后） |

---

## 附录 D：知识库查询接口说明

> 供 Step1 知识库自查使用。

**预置脚本** `search_failure_knowledge.py`：

```bash
python scripts/knowledge/search_failure_knowledge.py \
    --factor_name {factor_name} \
    --symbols {symbol1},{symbol2} \
    [--status failed]
```

**输出格式**：返回匹配的历史失败案例列表，包含 `exp_id`、`failure_reason`、`detail`、`date`。

**knowledge.db schema（相关表结构参考）：**
- `knowledge.entries`：归档条目表（含 factor_name、status、archive_path 字段）
- 详细 schema 文档：`docs/06_database/knowledge_db_schema.md`

---

## 版本变更记录

| 版本  | 日期                     | 变更摘要                                                     | 变更项    |
| :--: | ---------------------- | -------------------------------------------------------- | ------ |
| v1.0 | 2026-05-24T10:37+08:00 | 基于议题 A 评审（§0~§7 共 21 项）产出的正式版本                   | 21 项   |
| v1.1 | 2026-05-24T10:48+08:00 | 复审补写：signal_defined 生成角色 + Step1→2 数据传递契约 + IC 阈值修正 + 冷启动处理 | 4 项    |
|      |                        | 1. §5 Step8 signal_defined 生成角色：backtest runner 自动触发（A/B 级）, 人工回退路径同步备案               | §5     |
|      |                        | 2. §5 Step1→2 数据传递契约：增加 `knowledge_check.json` 中间文件定义                      | §5     |
|      |                        | 3. §4.1 IC 正值比强制线改回 >50%；>53% 降为优秀线；50%~53% 区间附加单调性证据              | §4.1   |
|      |                        | 4. §5 Step1 knowledge_check.json 冷启动处理：knowledge.db 为空时写入 {"found": false, "note": "cold_start"} | §5     |
|      |                        | **P0 必改（8 项）：**                                          |        |
|      |                        | 1. §0.5 审批流程表增加"验收人签字/日期"列                                | §0.5   |
|      |                        | 2. §0.5 增加退回/仲裁分支（最多 2 次退回 → 第 3 次 Owner 裁决）               | §0.5   |
|      |                        | 3. §4.1 IC 正值比提升至 >53%；增加 Universe<12 专属规则、分层单调性辅助判断 + override | §4.1   |
|      |                        | 4. §4.2 增加 Layer Q 等级映射表 + 评级归属表 + 复核触发条件                    | §4.2   |
|      |                        | 5. §5 Step2 增加 version_tag 自动注入机制 + 验收人核对规则                   | §5     |
|      |                        | 6. §5 Step7→8 改为分支流程（A/B → 归档；C → 条件归档 + Owner审批；D → 阻断）          | §5     |
|      |                        | 7. §7.3 增加验收人核查 SQL + 写入失败门禁规则                                | §7.3   |
|      |                        | 8. §5 Step4→5 增加 params_snapshot 参数传递规范                      | §5     |
|      |                        | **P1 建议改（7 项）：**                                          |        |
|      |                        | 9. §2.2 补充停复牌运行时处理规则                                           | §2.2   |
|      |                        | 10. §2.3 assert 改为硬阻断 + 独立预置脚本 `data_qc_check.py`              | §2.3   |
|      |                        | 11. §3.2 成交时间增加 trade_log 字段 + 验收人抽检规则                         | §3.2   |
|      |                        | 12. §4.3 P2 自洽性精确定义（Pearson r≥0.999, |diff|<1e-8, 绩效差≤0.1%, 固定种子） | §4.3   |
|      |                        | 13. §5 Step5→6 增加自动熔断（IR≤0 + 正值比≤45% → D 级）                   | §5     |
|      |                        | 14. §6.1 trading_days 改为系统日历自动填充 + 禁止手工填写                    | §6.1   |
|      |                        | 15. §6.2 增加 R1/R2/R3 硬约束 + W1/W2/W3 宽容规则                        | §6.2   |
|      |                        | **P2 可选（6 项）：**                                            |        |
|      |                        | 16. §1.3 增加注释：因子名须已存在于 methods.db                            | §1.3   |
|      |                        | 17. §2.1 上市未满 1 年→2 年；新增 free_float≥0.5；新增复权质量校验                 | §2.1   |
|      |                        | 18. §2.2 新增"暖机期受限"标记字段                                        | §2.2   |
|      |                        | 19. §3.2 滑点率增加 Layer Q 三档灵敏度审计（0.1%/0.3%/0.5%）                 | §3.2   |
|      |                        | 20. §6.3 新增预置脚本 `mark_abandoned.py` + 废弃标记扩展字段                  | §6.3   |
|      |                        | 21. §7.3 "三库写入"修正为"两库+归档目录"（factor_repository.db + knowledge.db + 报告目录） | §7.3   |
