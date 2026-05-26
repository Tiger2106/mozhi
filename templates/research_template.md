<!--
author: {{ author }}
created_time: {{ created_time }}
task_id: {{ task_id }}
version: v1.0
research_flow_version: phase4a_v1.0
preconditions: {{ preconditions_file }}
q_validators_used: G1, Q3, Q5
-->

# {{ research_name }} — {{ symbol }} {{ method }} 策略

{% if n_trades < 30 %}
## ⚠️ 样本量警告

**重要限制**：本报告所有绩效指标和风险评估指标均基于 **{{ backtest_days }} 天窗口中的 {{ n_trades }} 笔交易（n={{ n_trades }}）**。在此样本量下，所有百分比数字和风险评估指标均**不具有统计显著性**。报告功能为提供分析框架而非绩效验证。
{% endif %}

## 📊 数据分类声明

本报告包含以下类型的数据：
| 类别 | 占比 | 说明 |
|:----|:---:|:-----|
| ✅ **回测计算值** | {{ calc_pct }}% | 从回测 JSON + CSV 精确计算 |
| ⚠️ **观察性判断** | {{ obs_pct }}% | Observation 块中的策略解读和定性分析 |
| 🔮 **理论估计** | {{ est_pct }}% | 理论推导/外推/假设性结论 |

**生成时间**: {{ created_time }}
**标的代码**: {{ symbol }}
**策略配置**: {{ method }}, params={{ params }}
**回测周期**: {{ date_from }} ~ {{ date_to }}（{{ backtest_days }} 个交易日）
**数据来源**: {{ data_source }}
**前置条件文件**: {{ preconditions_file }}

---

## 一、{{ section1_title }}

{% if section1_content %}
{{ section1_content }}
{% else %}
<!-- TODO: 研究内容 -->
*待填充*
{% endif %}

### 1.1 分析框架

| 维度 | 指标 | 来源 | 数据分类 |
|:-----|:----|:----|:--------:|
| {{ dim1_name }} | {{ metric1 }} | {{ source1 }} | ✅ 回测计算值 |
| {{ dim2_name }} | {{ metric2 }} | {{ source2 }} | ✅ 回测计算值 |
| {{ dim3_name }} | {{ metric3 }} | {{ source3 }} | ⚠️ 观察性判断 |

### 1.2 核心发现

{% if findings %}
{% for finding in findings %}
- **{{ finding.label }}**: {{ finding.description }}
{% endfor %}
{% else %}
- **待填充**: 研究执行后补充核心发现
{% endif %}

---

## 二、{{ section2_title }}

{% if section2_content %}
{{ section2_content }}
{% else %}
<!-- TODO: 研究内容 -->
*待填充*
{% endif %}

### 2.1 数据表现

| 指标 | 值 | 备注 |
|:-----|:---:|:------|
| {{ metric_a }} | {{ value_a }} | ✅ 回测计算值 |
| {{ metric_b }} | {{ value_b }} | ⚠️ 观察性判断 |
| {{ metric_c }} | {{ value_c }} | ✅ 回测计算值 |

### 2.2 分析解读

{% if analysis %}
{{ analysis }}
{% else %}
*待填充*
{% endif %}

> 🔮 **Speculative**: 此部分为理论估计或改造性分析，非精确计算。

---

## 三、{{ section3_title }}

{% if section3_content %}
{{ section3_content }}
{% else %}
<!-- TODO: 研究内容 -->
*待填充*
{% endif %}

### 3.1 风险考量

| 风险维度 | 评估 | 分类 |
|:---------|:----:|:----:|
| {{ risk1_dim }} | {{ risk1_level }} | ⚠️ 观察性判断 |
| {{ risk2_dim }} | {{ risk2_level }} | ✅ 回测计算值 |
| {{ risk3_dim }} | {{ risk3_level }} | 🔮 理论估计 |

---

## 四、结论

{% if conclusion %}
{{ conclusion }}
{% else %}
*待填充*
{% endif %}

---

## Q 层验证结果

**验证流水线**: {{ q_validators_used }}  
**Task ID**: {{ task_id }}

| 验证器 | 结果 | 置信度 | 关键指标 | 备注 |
|:------|:----:|:------:|:---------|:-----|
| G1 Existence | {{ g1_result }} | {{ g1_confidence }} | {{ g1_metrics }} | {{ g1_note }} |
| Q3 Regime | {{ q3_result }} | {{ q3_confidence }} | 正收益状态={{ q3_positive }}/{{ q3_total }}, 集中度={{ q3_dominance }}% | {{ q3_note }} |
| Q5 Temporal | {{ q5_result }} | {{ q5_confidence }} | {{ q5_windows }}/{{ q5_total }} 窗口一致 | {{ q5_note }} |
| **Q 综合评级** | **{{ q_rating }}** | — | 瓶颈: {{ q_bottleneck }} | {{ q_summary }} |

### G1 检查详情（存在性验证）

| 检查 | 状态 | 值 | 阈值 |
|:----|:----:|:---:|:----:|
| C1 最小交易数 | {{ c1_status }} | {{ c1_value }} | N ≥ 30 |
| C2 多 Regime 覆盖 | {{ c2_status }} | K = {{ c2_value }} | K ≥ 2 |
| C3 多年度覆盖 | {{ c3_status }} | T = {{ c3_value }} 年 | T ≥ 2 年 |
| C4 非单段收益 | {{ c4_status }} | {{ c4_value }}% | < 40% |
| C5 信号密度 | {{ c5_status }} | {{ c5_value }}/年 | ≥ 12/年 |
| C6 样本分布 | {{ c6_status }} | {{ c6_value }}% | ≤ 50% |

---

## 附录

### A. 参数定义

| 参数 | 值 | 说明 |
|:-----|:---:|:------|
| {{ param1 }} | {{ param1_val }} | {{ param1_desc }} |
| {{ param2 }} | {{ param2_val }} | {{ param2_desc }} |

### B. 数据分类标准

| 类别 | 定义 |
|:-----|:------|
| ✅ **回测计算值** | 从回测 JSON + CSV 精确计算的数据，归因于确定性计算过程 |
| ⚠️ **观察性判断** | 研究者基于观察做出的定性分析和策略解读 |
| 🔮 **理论估计** | 基于理论推演的估计值，或对现有方法论的改造性应用 |

---

*本文由墨枢系统生成 | 墨衡 (moheng)*  
*生成时间: {{ created_time }}*  
*模板版本: research_template.md v1.0 (Phase 4a)*
