<!--
author: 玄知 (xuanzhi)
created_time: 2026-05-25T19:19+08:00
task: EXP-2026-INVFAC-002 Stage 2b 技术把关
-->

## 技术把关结论

**审查人**：玄知
**审查时间**：2026-05-25

### 数据一致性
✅ 确认

具体说明：
- **行情源一致性**：所有报告（design.md §1, summary_report.md §4自检, analysis_report.md §1.2）统一标注数据源为 `market_data.db`（统一行情源，截至2026-05-25），QFQ前复权，adj_base_date=2026-05-01。三处引用一致，无歧义。
- **300750排除记录清晰**：analysis_report.md 附录B明确标注300750(宁德时代)因adj_factor跳变+81.2%(2023-04-26送转股)排除；exp_results.json的stocks列表包含11只标的，不含300750；exp_summary/analysis报告均引用11只标的池。排除原因+影响+剩余数量均记录完整。
- **低波动不足标注一致**：exp_results.json中low_vol段为空字典，stability_results.json中low_vol全部标记"insufficient_data"，analysis_report.md附录B明确解释原因（低波动~360天×11只标的×3持有期后样本点<3）。三层信息一致。
- **关键指标交叉验证**：3个通过组合IC/p值在exp_results.json、exp_summary.md、summary_report.md §2.1、analysis_report.md §2.1之间完全一致（偏差<0.0001）。FDR校正结果：3/12 rejected，单调性校正后q=0.0404，与报告一致。L3通过的12组合与exp_results.json中stability_L3总结(pass_rate=0.444)一致。
- **敏感性分析稳健**：sensitivity_analysis.json baseline(0.80,0.30)的IC值与exp_results.json一致（仅在小数点后第5位有舍入差异，<1e-5误差），9格扫描0翻转(0/243, data_points=108)。
- **QA结论匹配**：analysis_report.md §6中墨萱QA确认IC偏差<0.0001、p值完全匹配、FDR 3/12 rejected、L3 12/27通过，与原始JSON数据完全一致。

### 架构合理性
✅ 确认

具体说明：
- **三因子设计一致性**：exp_invfac002三因子（TrendQuality + l_vol_rsi_std + l_str_kdj_k）与EXP-002 Phase 1报告中8个负IC因子中选择相符，R001共识锁定项完全继承。三因子覆盖趋势、量能、技术指标三个独立维度，机械独立性高，通过一个则泛化能力高于单维度结论。
- **三层检验形成闭环**：
  - L1（IC符号转换）：在状态子集内做符号反转，非全样本统一反转。反转仅在子集内进行，无前视偏差。
  - L2（FDR BH校正）：标准BH过程+单调性校正，q=0.05。27组合中12个原始检验（剔除15个insufficient_data），3/12通过BH校正。
  - L3（稳定性检验）：时间切片(4/4一致)+滚动(flip_rate<30%)+横截面(11/11方向一致)+OOS(方向一致)，4项中3/4即通过。所有通过组合checks_passed≥3/4。
  - 闭环完整性：L1→L2→L3层层递进，未跳步，过拟合风险自检评分20/100合理。
- **参数设计自洽**：
  - 随机种子42固定，Bootstrap n=10000
  - 暖机期(2021)锁定波动率阈值防止前视偏差
  - 3状态(高/中/低波动)×3持有期(5/10/20日)形成27组合网格
  - 敏感性分析覆盖3×3=9组分位数阈值，稳健性判定规则（≥7/9一致）明确
- **潜在设计小问题**（不影响结论，供参考）：
  - 设计文档§2.2将样本内(2022-01~2024-06)与样本外(2024-07~2025-12)分开，但实际执行中IC检验似乎使用了2022-01~2025-12完整周期，并未严格按IS/OOS拆分做IC主检验的交叉验证。OOS在L3中仅用于方向一致性判断。建议后续方案在design.md中明确IC主检验的样本窗口。

### 复现性
⚠️ 部分缺失

具体说明：
- **代码版本标注**：summary_report.md §4自检I6标注"mozhi_platform为非Git仓库，标注'工作副本(未提交)'"，analysis_report.md §1.3给出完整的关键模块列表(run_exp_invfac002.py, exp_factors.py, exp_market_state.py, exp_bootstrap.py, exp_stability.py, data_qc_check.py)。但所有模块未做代码快照或checksum锁定——若后续修改了任一模块，当前结果无法复现。
- **环境信息**：analysis_report.md 附录C记录了OS(Windows 11 10.0.26200)、Python(3.14.3)、numpy(2.4.4)、pandas(3.0.1)、matplotlib(3.10.9)。但未提供完整的`pip freeze`或`conda list`输出，缺少sqlite3/argparse/datetime等标准库版本（虽为标准库，但应记录）。
- **正向复现能力**：随机种子42已固定，因子计算逻辑在design.md §3.1以伪代码给出，Bootstrap置换逻辑在design.md §3.3以伪代码给出。因设计文档伪代码与实际脚本不完全一致（可能无代码级一一对应），复现需依赖原始代码文件。
- **建议**：未来试验无论是否使用Git，应在试验完成时自动生成代码目录的目录快照(tar/zip)或至少使用`sha256sum`对关键脚本生成文件哈希，并将哈希值写入报告。

### 结论一致性
✅ 合理

具体说明：
- **"观察，置信度中"与指标匹配**：
  - l_vol_rsi_std/20d高波动：IC=+0.0478(FDR BH通过, L3通过) → 正向反转确认 ✓
  - l_str_kdj_k/10d高波动：IC=+0.0197(FDR BH通过, L3通过) → 正向反转确认 ✓
  - TrendQuality/20d高波动：IC=-0.0202(FDR BH通过, L3通过) → 已修正标注为"负向增强"（反转后IC仍为负），非反转信号。修正正确。
  - 判定"观察"而非"确认"的依据（仅高波动有效、IC绝对值偏小、11只标的代表性有限）在summary_report中已充分陈述。
  - 过拟合风险20/100（偏低），结论的保守程度与数据证据力度匹配。
- **后续建议合理**：
  - 信号标注"橙色"进入候选池（低置信度决策）合理
  - 扩展全A股重新验证（标的特异性控制）
  - 3个月观察期（时间边界控制）
  - 未通过24组合正式拒绝归档

### 整体结论
✅ 同意归档

**审定要点**：架构设计合理（三因子×三状态×三层检验形成闭环），数据一致性已通过墨萱QA验证并与原始数据完全匹配，方法论稳健（敏感性0翻转/243，过拟合风险20/100），结论保守恰当（"观察，置信度中"）。
