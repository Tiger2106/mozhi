# 右侧交易情绪-流动性共振 Phase 0 总体框架设计

**作者**: 墨衡 🖋️
**创建时间**: 2026-05-29T09:15:00+08:00
**版本**: v2.0
**状态**: 已签署 · 版本: v2.0 · Owner签字: ✅ 2026-05-29
**依据**: 辩论总结 `辩论总结_会签_v1.0.md` / ARCH001_v1
**审核反馈**: 墨萱评审 C1 + 玄知评审 X-A1/X-C1 + Owner 评审 O1/O2/O3
**修复说明**: v1→v2 修复项参见 §10 变更日志

---

## 目录

0. 设计承诺清单（辩论结论→设计决策映射）
1. 系统架构全景（4层）
2. 模块划分及职责
3. 数据流（数据源 → 计算 → 判定 → 输出）
4. 关键数据结构定义
5. 与现有系统的集成关系
6. 否决制 / CONDITIONAL PASS 灰度层位置
7. 调度层适配器设计
8. 轻架构考量与模块计数
9. 附录：Phase 0 → Phase 1 演进路线
10. 变更日志（v1→v2）

---

## 0. 设计承诺清单

| # | 辩论结论约束 | 本设计对应 | 是否覆盖 |
|:-:|:------------|:-----------|:--------:|
| 1 | 情绪代理：VIX波动率/舆情情绪打分（二选一，单源可复现） | §2.1 DCM 模块 — 选型 **波动率代理**（HV z-score → Phase 0.5 升级 IV） | ✅ |
| 2 | 流动性代理：换手率/买卖价差 | §2.2 LQM 模块 — 选型 **换手率**（L2 体系，数据就绪） | ✅ |
| 3 | 共振判定：同极端分位数同时触发（20日z-score联动） | §2.3 RSM 模块 — 20日滚动 z-score + 极值联合检测 | ✅ |
| 4 | 双源校验：双源缩量版，来源独立性验证 | §2.4 DSV 模块 — 轻量双源校验（不同方法/不同窗口） | ✅ |
| 5 | 否决制：sanity check 不通过一律否决 | §2.5 GKV 模块 + §6 硬否决位置 | ✅ |
| 6 | CONDITIONAL PASS：连续5日共振>0.6+双源校验通过，仓位上限≤50% | §2.6 CPE 模块 + §6.2 条件放行逻辑 | ✅ |
| 7 | 调度层适配器：事件驱动vs定时轮询"不兼容"限定在调度层 | §7 SCL 适配器 — 调度层唯一抽象，计算引擎零侵入 | ✅ |
| 8 | 架构轻是加分项 | §8 模块计数——8模块（含调度层），6核心计算模块 | ✅ |

---

## 1. 系统架构全景（4层）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Layer 4: 信号输出层                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  SG (Signal Generator) / CPL (Signal Protocol v1 Adapter)       │   │
│  │  职责：┌→ Signal Protocol v1 格式信号                              │   │
│  │        ├→ .done 信号文件写入                                     │   │
│  │        └→ 日内/日终信号路由                                     │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                          Layer 3: 决策判定层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ │
│  │  GKV (门控)  │  │  CPE (条件)  │  │  EMA (应急熔断)  [Phase 0.5+] │ │
│  │  Sanity Check│  │  Cond. Pass  │  │  连续亏/回撤超限熔断           │ │
│  │  否决制执行   │  │  灰度放行    │  │                                ｜ │
│  └──────▲───────┘  └──────▲───────┘  └────────────────────────────────┘ │
│         │                 │                                              │
│         │     ┌───────────┘                                              │
│         │     │                                                          │
│  ┌──────┴─────┴──────────────────────────────────────────────────────┐  │
│  │  RSM (Resonance State Machine) — 共振状态机                       │  │
│  │  职责：共振强度计算 + 状态转换（无共振→预警→共振→衰减）             │  │
│  │  内部结构: _compute_strength() 算法层 + _transition_state() 状态层 │  │
│  │  并行输入: 接收 ZNM 的 z-score（与 DSV 无依赖关系）                 │  │
│  └──────────────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────┤
│                          Layer 2: 计算引擎层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ │
│  │  ZNM 模块    │  │  DSV 模块    │  │  DSV-2 (辅助校验)              │ │
│  │  z-score归一  │  │  双源校验    │  │  降级: 无双源→单源+置信度衰减   │ │
│  │  (20日滚动)   │  │  (缩量版)    │  │                                │ │
│  │               │  │  并行于 RSM  │  │                                │ │
│  │               │  │  互不依赖    │  │                                │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────────────────────────┘ │
│         │                 │                                              │
│         ▼                 ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  LB (Lookback Buffer) — 20日滚动数据缓存                          │   │
│  │  (内存DF + 文件持久化双存储)                                       │   │
│  │  职责：历史数据读取 + RSM 状态持久化 + 滚动窗口维护                 │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                          Layer 1: 数据采集层                              │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────────────┐ │
│  │  DCM 模块    │  │  LQM 模块    │  │  VIX-Proxy 计算器              │ │
│  │  波动率代理   │  │  换手率计算   │  │  (Phase 0: HV → Phase 0.5: IV) │ │
│  │  (A50价格)   │  │  (vol/free_  │  │                                │ │
│  │              │  │   float)     │  │                                │ │
│  └──────┬───────┘  └──────┬───────┘  └────────────────────────────────┘ │
│         │                 │                                              │
│         ▼                 ▼                                              │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  DataBridge (数据桥) — 统一数据入口                                │   │
│  │  职责：A50 日线 OHLCV + free_float 获取，缓存策略，错误重试         │   │
│  │  ┌─ 信号职责: 推送当日新数据给计算管线                              │   │
│  │  ├─ 查询职责: 供 LB 回放历史数据（离线/回测场景）                   │   │
│  │  └─ ⚠️ 职责分离点: 信号推送使用独立通道，历史回放使用查询接口        │   │
│  │  对接：data_contract.py / etl_normalizer.py / source_registry.json  │   │
│  │  复用：现有 morning_pipeline 的数据管线                              │   │
│  └──────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│                    Layer 0: 调度层（非侵入、可替换）                       │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  SCL (Scheduling Layer Adapter)                                  │   │
│  │  职责：将调度机制（cron轮询/事件驱动）转化为统一调用接口              │   │
│  │  封装：run_once() / force_run(date: "YYYY-MM-DD") / on_event()   │   │
│  │  约束：不嵌入业务逻辑，仅通过 pipeline.run() 统一接口调用            │   │
│  │  韧性：max_retries=1, fallback=skip_silently                      │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.1 分层责任边界

| 层 | 依赖方向 | 能否独立测试 | 调试角色 |
|:--:|:--------|:------------:|:---------|
| L4 信号输出 | 依赖 L3 | ✅ 可 mock L3 输出单独测试 | 墨萱 |
| L3 决策判定 | 依赖 L2 | ✅ 可 mock L2 数据单独测试 | 墨衡 |
| L2 计算引擎 | 依赖 L1 | ✅ 可 mock L1 数据单独测试 | 墨衡 |
| L1 数据采集 | 无下层依赖 | ✅ 纯数据层，独立验证 | 墨衡 |
| L0 调度层 | 无下层依赖 | ✅ 适配器模式，可替换测试 | 玄知 |

### 1.2 模块依赖规则

```
L4 (SG) → L3 (CPE → GKV)
L3 (GKV) → 并行接收 RSM + DSV 结果     # GKV 依赖 RSM 的共振强度 + DSV 的校验结果
L3 (RSM) → L2 (ZNM)                     # RSM 仅依赖 ZNM 的 z-score 输出（不依赖 DSV）
L2 (DSV) → L2 (ZNM)                     # DSV 同样依赖 ZNM 的 z-score 输出（与 RSM 平行）
L2 (ZNM, DSV) → L1 (DCM, LQM)
L1 (DCM, LQM) → DataBridge
L0 (SCL) → 不嵌入业务逻辑，仅通过 pipeline.run() 统一接口调用计算引擎
```

**关键更新说明（v1→v2）**:
- **RSM 与 DSV 为并行关系**：两者均以 ZNM 的 z-score 为输入，互不依赖，计算结果并行送入 GKV 做门控判断
- **SCL 措辞修正**：从"不依赖 L1-L4"修正为"不嵌入业务逻辑，仅通过 pipeline.run() 统一接口调用"——SCL import 级间接依赖无法避免，但确保不侵入计算引擎内部实现

**严格禁止**:
- L2 直接调用 L4 接口
- L3 绕过 L2 直接读取原始数据
- L0 混入计算逻辑

---

## 2. 模块划分及职责

### 2.1 DCM — 波动率代理模块 (Data Collection: Volatility)

| 属性 | 定义 |
|:----|:------|
| **输入** | A50 日线 OHLC（来自 DataBridge） |
| **计算** | 20日滚动年化HV = std(log(close/close[-1]), 20d) × sqrt(252) |
| **输出** | `raw_volatility_series: pd.Series`（每日1个值） |
| **Phase 0 选型** | **历史波动率 (HV)** — 单源、可复现、零外部依赖 |
| **Phase 0.5 升级** | HV → IV(implied volatility, 从期权数据推导), 或引入 iVIX |
| **数据源** | Tushare / AKShare A50 日线 (close) |
| **复现验证** | 同一输入 → 同一输出（确定性计算） |
| **异常处理** | 缺失数据→前值填充（最多3日）；超3日→标记 `data_gap`，本次跳过 |

**为什么选 HV 而非 IV 作为 Phase 0**:
- 辩论结论明确 "单源可复现"——HV 是纯粹的价格衍生量
- IV 需要期权数据，引入额外的数据源和计算复杂度
- Phase 0 目标验证共振框架有效性，IV vs HV 的精度差异可在 Phase 1 补

### 2.2 LQM — 换手率计算模块 (Liquidity: Turnover)

| 属性 | 定义 |
|:----|:------|
| **输入** | A50 volume + free_float（来自 DataBridge） |
| **计算** | turnover_rate = volume / free_float（量纲: 无量纲比值） |
| **输出** | `raw_turnover_series: pd.Series`（每日1个值） |
| **选型依据** | L2 层已有定义（见 ARCH001_v1），数据已就绪 |
| **free_float 口径** | 锁定为 Tushare daily_basic.float_share（ARCH001 决议） |
| **Phase 1 扩展** | 支持 买卖价差（需分钟级数据管线前置） |
| **异常处理** | free_float 为 0（停牌/缺失）→ 标记 `invalid_turnover`，本次跳过 |

### 2.3 RSM — 共振状态机模块 (Resonance State Machine)

| 属性 | 定义 |
|:----|:------|
| **输入** | ZNM 输出的波动率 z-score + 换手率 z-score + **前次状态**（从LB读取） |
| **计算** | 共振检测 + 共振强度 + 状态转换 |
| **输出** | `resonance_signal: dict`（含状态、强度、持续时间） |
| **内部结构** | `_compute_strength()` — 算法层（L2.5 计算）+ `_transition_state()` — 状态层（L3 判定，依赖算法层输出） |

#### 共振检测核心算法

```
RESONANCE_MIN_STRENGTH = 0.6   # 全局常量，GKV 否决基线和 CPE 条件放行共用

def detect_resonance(vol_zscore, turn_zscore,
                     previous_state: dict = None,
                     quantile_threshold=1.5):
    """
    输入: 波动率z-score, 换手率z-score（均为20日滚动）
         previous_state: 前次运行结果 {state, duration, strength_seq}（从LB读取）
         首次运行/无历史时 previous_state=None
    同极端分位数同时触发判断:
    """
    # 1. 提取极值尾部 [算法层: _compute_strength()]
    vol_extreme = abs(vol_zscore) > quantile_threshold
    turn_extreme = abs(turn_zscore) > quantile_threshold

    # 2. 方向一致性
    same_direction = (vol_zscore > 0) == (turn_zscore > 0)

    # 3. 共振强度 (0.0 ~ 1.0)
    if vol_extreme and turn_extreme and same_direction:
        resonance_strength = sqrt(vol_zscore² + turn_zscore²) / (quantile_threshold * sqrt(2))
        resonance_strength = clip(resonance_strength, 0.0, 1.0)
    else:
        resonance_strength = 0.0

    # 4. 方向标记
    direction = "POSITIVE" if vol_zscore > 0 else "NEGATIVE"

    # 5. 状态转换 [状态层: _transition_state()]
    new_state, state_duration = _transition_state(
        strength=resonance_strength,
        previous_state=previous_state
    )

    return {
        "resonance": vol_extreme and turn_extreme,
        "strength": round(resonance_strength, 4),
        "direction": direction,
        "state": new_state,
        "state_duration": state_duration,
        "vol_extreme": bool(vol_extreme),
        "turn_extreme": bool(turn_extreme)
    }
```

#### 状态转换函数

```
def _transition_state(strength, previous_state: dict = None):
    """
    跨日程状态机 — 依赖 LB 提供的上次状态信息
    previous_state: {"state": str, "duration": int, "last_update": str}
    首次运行时 previous_state = None → 初始化为 NONE

    状态过期策略:
    - WARN 状态保持 > 5 日未触发 ACTIVE → 自动重置为 NONE
    - DECAY 状态保持 > 10 日未恢复 NONE → 自动重置为 NONE
    """
    # 首次运行：初始化默认
    if previous_state is None:
        prev_state = "NONE"
        prev_duration = 0
    else:
        prev_state = previous_state.get("state", "NONE")
        prev_duration = previous_state.get("duration", 0)

    # 状态过期检查
    if prev_state == "WARN" and prev_duration >= 5 and strength < 0.3:
        return "NONE", 0
    if prev_state == "DECAY" and prev_duration >= 10 and strength == 0.0:
        return "NONE", 0

    # 状态转移
    if prev_state == "NONE":
        if strength > 0.3:
            return "WARN", 1
        return "NONE", 0

    elif prev_state == "WARN":
        if strength > RESONANCE_MIN_STRENGTH and prev_duration >= 1:
            return "ACTIVE", 1  # 满足2日条件 → 进入ACTIVE
        if strength > 0.3:
            return "WARN", prev_duration + 1
        # 强度回落
        if strength <= 0.3 and prev_duration >= 1:
            return "NONE", 0
        return "WARN", prev_duration + 1

    elif prev_state == "ACTIVE":
        if strength > RESONANCE_MIN_STRENGTH:
            return "ACTIVE", prev_duration + 1
        if strength < 0.3:
            return "DECAY", 1
        return "ACTIVE", prev_duration + 1

    elif prev_state == "DECAY":
        if strength >= 0.3:
            return "WARN", 1  # 强度回升 → 回预警
        if strength == 0.0:
            return "NONE", 0  # 完全恢复
        return "DECAY", prev_duration + 1

    return "NONE", 0
```

#### 共振状态机

```
        ┌────────────────────────────────────────────────────────┐
        │                   NONE (无共振)                         │
        │  强度==0，正常市场状态                                   │
        │  过期重置: WARN>5日无进展 / DECAY>10日未恢复             │
        └──────────┬─────────────────────────────────────────────┘
                   │ 共振触发: strength > 0.3
                   ▼
        ┌────────────────────────────────────────────────────────┐
        │               WARN (预警观察)                           │
        │  强度∈(0.3, RESONANCE_MIN_STRENGTH]，持续1-2日          │
        │  行为: 写入预警日志，不下单                              │
        │  超5日无进展 → 自动重置为 NONE                          │
        └──────────┬─────────────────────────────────────────────┘
                   │ 持续共振: strength > RESONANCE_MIN_STRENGTH 且 ≥ 2日
                   ▼
        ┌────────────────────────────────────────────────────────┐
        │              ACTIVE (共振生效)                          │
        │  强度∈(RESONANCE_MIN_STRENGTH, 1.0]，可产生信号          │
        │  行为: 进入GKV门控 → 若通过则生成信号                    │
        └──────────┬─────────────────────────────────────────────┘
                   │ 强度衰减: strength < 0.3 持续 3 日
                   ▼
        ┌────────────────────────────────────────────────────────┐
        │              DECAY (衰减观察)                           │
        │  强度∈(0, 0.3]，残留共振                               │
        │  行为: 维持已有信号但不再产生新信号                       │
        │  超10日未恢复 → 自动重置为 NONE                         │
        └──────────┬─────────────────────────────────────────────┘
                   │ 完全恢复: strength == 0 持续 5 日
                   ▼
                   NONE
```

### 2.4 DSV — 双源校验模块 (Dual-Source Verification)

**缩量版含义**: 不是"全双源管线"，而是在可用数据范围内做最小的独立验证。

| 验证维度 | 主源 | 辅源 | 独立性条件 |
|:---------|:-----|:-----|:----------|
| **波动率** | 20日HV (close-to-close) | 20日Parkinson HV (high-low) 或 5日滚动HV | 不同计算窗口 / 不同价格口径 |
| **换手率** | 日换手率 (volume/free_float) | 5日滚动平均换手率 | 不同聚合窗口 |

**独立性定位（Phase 0）**: 当前采用 **计算方法独立**（HV vs Parkinson HV 使用不同计算公式），而非数据来源独立。HV 和 Parkinson HV 共享同一 close 数据源（尽管 Parkinson 额外使用 high/low），严格意义上不满足"数据源完全独立"。Phase 1+ 升级为"数据来源独立"（如引入行情商 second data feed 或期权隐含数据作为辅源）。

**校验逻辑**:
```
def dual_source_verify(vol_primary, vol_secondary, turn_primary, turn_secondary):
    # 0. guard clause: 序列为常数时 Spearman 返回 NaN
    if std(vol_primary) == 0 or std(vol_secondary) == 0:
        return {"passed": False, "score": 0.0}
    if std(turn_primary) == 0 or std(turn_secondary) == 0:
        return {"passed": False, "score": 0.0}

    # 1. 波动率双源一致性
    vol_corr = spearman(vol_primary[-20:], vol_secondary[-20:])
    vol_pass = vol_corr > 0.7  # Spearman > 0.7 = 方向一致

    # 2. 换手率双源一致性
    turn_corr = spearman(turn_primary[-20:], turn_secondary[-20:])
    turn_pass = turn_corr > 0.7

    # 3. 综合判定
    if vol_pass and turn_pass:
        return {"passed": True, "score": min(1.0, (vol_corr + turn_corr) / 2)}
    elif vol_pass or turn_pass:
        return {"passed": False, "score": 0.5, "partial": True}
    else:
        return {"passed": False, "score": 0.0, "partial": False}
```

**缩量策略**: 当辅源不可用时（如 HV -> Parkinson HV 需OHLC数据，而当前只有close），降级为单源 + 置信度衰减 0.8 系数。

**辅源可用性检测**: DSV 初始化时检查 DataBridge 返回数据的 `available_dimensions` 字段（需 DataBridge 提供 `["close", "high", "low", "volume", "free_float"]` 维度声明），若缺少 high/low 则跳过 Parkinson HV 支路。

### 2.5 GKV — 门控&否决模块 (Gatekeeper & Veto)

**配置常量**: `RESONANCE_MIN_STRENGTH = 0.6`

**否决制位置**: 唯一硬否决点，位于共振生效后、信号生成前。

```
input: resonance_signal (from RSM)
input: dsv_result (from DSV)

1. [否决基线] resonance_signal["strength"] < RESONANCE_MIN_STRENGTH → VETO
2. [否决基线] len(resonance_days) < 2 → VETO (持续不足2日)
3. [DSV否决] dsv_result["passed"] == False and not dsv_result["partial"] → VETO
4. [数据否决] 当日 DCM 或 LQM 有 data_gap / invalid → VETO
5. [方向否决] resonance_signal["direction"] == "NEGATIVE" 且 标的无保护 → WARN（非否决，仅标记）

VETO → 写入 `.vetoed` 日志，信号不生成
PASS → 进入 CPE 条件放行评估
```

**否决制优先级**: 任一条否决触发 → 信号不输出。否决不可叠加覆盖。

### 2.6 CPE — 条件放行评估模块 (Conditional Pass Evaluator)

**配置常量**: `RESONANCE_MIN_STRENGTH = 0.6`（与 GKV 共用同一阈值）

```
input: resonance_signal (持续 N 日记录)
input: gkv_result (PASS)
input: dsv_result (DSV 校验结果)

评估:
  1. 连续5日共振强度 > RESONANCE_MIN_STRENGTH?
     AND DSV 双源校验通过 (passed == True)?
     YES → CONDITIONAL_PASS (仓位上限 ≤ 50%)
           理由: 持续高共振 + 独立验证通过 → 信号可信度高，但保守限仓
     NO  → FULL_PASS (仓位无额外限制，但仍受整体风控约束)
           理由: 异常度不足以触发限仓条件，视为常规信号

特殊规则:
  - DSV partial=True 时 → CPE 自动视为 FULL_PASS
    (partial=True 说明双源仅一源通过，不可触发 CONDITIONAL_PASS)
  - CONDITIONAL_PASS 信号生效窗口：T+1 开盘 30 分钟内有效
  - 仓位上限 50% 受外部风控约束，取 min(position_cap, 风控上限)

CONDITIONAL_PASS 输出示例:
{
  "status": "CONDITIONAL_PASS",
  "position_cap": 0.5,
  "reason": "连续5日共振>0.6 + 双源校验通过 → 仓位上限≤50%",
  "resonance_days": 5,
  "avg_strength": 0.72
}

FULL_PASS 输出示例:
{
  "status": "FULL_PASS",
  "position_cap": 1.0,
  "reason": "条件放行条件未满足 → 正常仓位",
  "resonance_days": 3,
  "avg_strength": 0.68
}
```

**⚠️ v1→v2 修正说明**: v1 中 YES/NO 分支含义写反（YES→FULL_PASS, NO→CONDITIONAL_PASS）。实际逻辑应为：条件满足（连续5日>0.6 + 双源通过）→ CONDITIONAL_PASS（仓位受限），这是辩论结论中"双源校验通过+持续高共振"的灰度放行场景；条件不满足 → FULL_PASS（正常仓位）。

### 2.7 SG — 信号生成模块 (Signal Generator)

将 CPE 输出映射为 Signal Protocol v1 格式信号。

```python
def generate_signal(cpe_result):
    signal = {
        "signal_id": str(uuid.uuid4()),
        "symbol": CONFIG.A50_SYMBOL,    # 如 "510050" (A50 ETF)
        "direction": "BUY" if resonance_direction == "POSITIVE" else "SELL",
        "confidence": cpe_result["avg_strength"],
        "horizon": "short",
        "signal_type": "trend",
        "timestamp": datetime.now(UTC+8),
        "protocol_version": "1.0",
        "extras": {
            "resonance.avg_strength": cpe_result["avg_strength"],
            "resonance.duration": cpe_result["resonance_days"],
            "resonance.status": cpe_result["status"],
            "risk.position_cap": cpe_result["position_cap"],
            "resonance.verdict": cpe_result["reason"]
        }
    }
    return Signal(**signal)
```

### 2.8 SCL — 调度层适配器 (Scheduling Layer)

见 §7 专章。

---

## 3. 数据流

### 3.1 正常流程（一次性全流程）

```
时间轴: [T-20, T] 数据历史积累 → T 日开盘后执行

Step 0: SCL 触发 run_once()
  │
├─ Step 0.5A: 从 LB 读取历史 z-score 序列 + RSM 前次状态
│            (用于 20 日滚动计算 + 状态机恢复)
│
Step 1: DataBridge 获取 A50 日线数据（最近 40 日，含 20 日滚动窗 buffer）
  │
Step 2: DCM 计算 20日滚动年化HV
  │  → raw_volatility_series (len=21)
  │
Step 3: LQM 计算 换手率
  │  → raw_turnover_series (len=21)
  │
Step 4: ZNM 标准化
  │  → z_vol = (vol - mean_20d) / std_20d
  │  → z_turn = (turn - mean_20d) / std_20d
  │
  ┌─────────┬──── 并行分支 ────┬─────────┐
  │                             │
  ▼                             ▼
Step 5a: RSM 共振检测          Step 5b: DSV 双源校验
  → resonance_signal             → dsv_result
  (状态/强度/方向)               (vol_corr, turn_corr,
                                  passed/partial/failed)
  │                             │
  └─────────┬─────────┬─────────┘
            │ (并行结果合并)
            ▼
├─ Step 5.5: (可选) 将 RSM 新状态即时写入 LB（持久化当前日状态）
│
Step 6: GKV 门控 (否决制)
  │  → VETO → 终止 (写 .vetoed 日志)
  │  → PASS → 继续
  │
Step 7: CPE 条件放行评估
  │  → CONDITIONAL_PASS  or  FULL_PASS
  │
Step 8: SG 信号生成
  │  → Signal Protocol v1 信号文件
  │  → .done 信号写入
  │
├─ Step 9.5A: 更新 LB — 追加当日 z-score/hv/turnover，裁剪至 20 日窗
├─ Step 9.5B: 更新 LB — 写入当日 RSM 状态 + 持续天数
│            (若 Step 5.5 已写入则此处为确认写入)
│
Step 10: 输出 → signals/signals/ (等待调度层消费)
```

**关键说明**:
- **RSM 与 DSV 并行执行**: 两者均以 ZNM 输出的 z-score 为输入，互不依赖。GKV 同时接收两者的输出。
- **LB 读写时机**: run 开始前从 LB 恢复状态，run 完成后将新状态持久化回 LB。
- **首次运行时 LB 为空**: RSM 前次状态初始化 `{"state": "NONE", "duration": 0}`；z-score 序列初始化 `[]`。
- **幂等性**: 同一天多次调用 run_once()，Step 9.5A/9.5B 采用"覆盖写入"策略（以当日 date 为键），确保同一日数据不重复累积。

### 3.2 日内触发流程（定时轮询）

```
每 N 分钟（默认 30min）:
  1. SCL 调用 run_once()
  2. 检查是否有新数据 (DataBridge.get_latest())
  3. 无新数据 → 跳过 (节省计算资源)
  4. 有新数据 → 执行 Step 0.5A-10
```

### 3.3 异常流程

```
数据缺失:
  DCM/LQM → data_gap ≤ 3d → 前值填充 → 标记 gap
  data_gap > 3d → 标记 SKIP → GKV 否决

DSV 降级:
  辅源不可用 → 单源 + 置信度衰减 → DSV partial=True
  GKV 不否决 partial True
  CPE: partial=True → 自动 FULL_PASS (不可触发 CONDITIONAL_PASS)

计算异常:
  除零/NAN → 捕获标记为 FAILED → 写入 .failed 日志 → 不生成信号
  DSV Spearman: std==0 → guard clause 提前返回假

RSM 状态机异常:
  LB 读取失败/数据损坏 → 初始化为 NONE + 写入 warning 日志
  LB 写入失败 → 不阻断流程，下次 run 从上次状态恢复
```

### 3.4 数据流图（简化）

```
┌──────────┐   ┌──────────┐
│ A50 日线  │   │ free_float│
│ (OHLCV)   │   │ (流通股本) │
└─────┬────┘   └─────┬────┘
      │              │
      ▼              ▼
┌──────────────────────────┐
│       DataBridge         │
│  · 数据获取+缓存         │
│  · 缺失数据前值填充      │
│  · 统一日期索引          │
│  · 职责: 信号推送/历史回放│
│    (职责分离点见 §5.1)   │
└──────────┬───────────────┘
           │
     ┌─────┴─────┐
     │           │
     ▼           ▼
┌──────────┐ ┌──────────┐
│   DCM    │ │   LQM    │
│ HV计算   │ │ 换手率    │
└────┬─────┘ └────┬─────┘
     │           │
     ▼           ▼
┌──────────────────────────┐
│  ZNM — z-score 标准化    │
│  · vol z-score           │
│  · turn z-score          │
└──────────┬───────────────┘
           │
     ┌─────┴─────┐
     │ (并行分支) │
     ▼           ▼
┌──────────┐ ┌──────────┐
│ RSM      │ │ DSV      │ ← 并行，互不依赖
│ 共振检测  │ │ 双源校验  │
│ 状态机   │ │           │
└────┬─────┘ └────┬─────┘
     │           │
     └─────┬─────┘
           │ (合并)
           ▼
┌──────────────────────────┐
│    GKV 门控（否决制）      │
│  否决 → 写 .vetoed → 终结 │
│  通过 → 进入 CPE          │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│    CPE 条件放行评估        │
│  · 连续5日>0.6 + DSV通过? │
│  YES→CONDITIONAL(仓位受限)│
│  NO→FULL_PASS(正常仓位)   │
│  partial→自动FULL_PASS    │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│    SG 信号生成             │
│  · Signal Protocol v1    │
│  · extras 携带共振元数据  │
│  · .done 信号文件         │
└──────────┬───────────────┘
           │
           ▼
   signals/signals/ (等待消费)

数据驱动（非流程驱动）:
┌──────────────────────────┐
│  LB (Lookback Buffer)    │
│  · 历史 z-score 序列     │
│  · RSM 前次状态           │
│  · 读: Step 0.5A         │
│  · 写: Step 5.5/9.5A-B   │
└──────────────────────────┘
```

---

## 4. 关键数据结构定义

### 4.1 共振信号内部数据结构 (resonance_signal.json)

```json
{
  "status": "READY",
  "task_id": "resonance_20260529",
  "timestamp": "2026-05-29T10:00:00+08:00",
  "raw_data": {
    "symbol": "510050",
    "date": "2026-05-29",
    "volatility_hv": 0.1853,
    "turnover_rate": 0.0245,
    "vol_zscore": 2.13,
    "turn_zscore": 1.87
  },
  "resonance": {
    "detected": true,
    "strength": 0.78,
    "direction": "POSITIVE",
    "state": "ACTIVE",
    "state_duration": 3,
    "quantile_threshold": 1.5
  },
  "verification": {
    "source": "dual_source",
    "vol_spearman": 0.85,
    "turn_spearman": 0.79,
    "passed": true,
    "partial": false,
    "degraded": false
  },
  "gatekeeping": {
    "vetoed": false,
    "veto_reason": null,
    "sanity_checks": {
      "strength_above_min": true,
      "duration_above_min": true,
      "dsv_passed": true,
      "data_complete": true
    }
  },
  "conditional_pass": {
    "status": "FULL_PASS",
    "position_cap": 1.0,
    "consecutive_resonance_days": 3,
    "consecutive_above_threshold": false,
    "dsv_verified": true
  }
}
```

### 4.2 输出信号 (Signal Protocol v1 兼容)

```json
{
  "signal_id": "550e8400-e29b-41d4-a716-446655440000",
  "symbol": "510050",
  "direction": "BUY",
  "confidence": 0.7800,
  "horizon": "short",
  "signal_type": "trend",
  "timestamp": "2026-05-29T10:00:00+08:00",
  "protocol_version": "1.0",
  "extras": {
    "resonance.avg_strength": 0.78,
    "resonance.duration": 3,
    "resonance.status": "FULL_PASS",
    "resonance.verdict": "条件放行条件未满足 → 正常仓位",
    "risk.position_cap": 1.0
  }
}
```

### 4.3 否决日志 (.vetoed)

```json
{
  "veto_id": "veto_20260529_001",
  "timestamp": "2026-05-29T10:00:00+08:00",
  "status": "VETOED",
  "trigger_reason": "DSV双源校验不通过: turn_spearman=0.32 < 0.7",
  "sanity_checks": {
    "strength_above_min": true,
    "duration_above_min": true,
    "dsv_passed": false,
    "data_complete": true
  },
  "resonance_state": "WARN",
  "resonance_strength": 0.45
}
```

### 4.4 20日滚动缓存结构 (lookback_buffer.pkl / .json)

```json
{
  "symbol": "510050",
  "last_updated": "2026-05-29",
  "rolling_window": 20,
  "volatility_raw": [0.12, 0.14, 0.15, 0.13, ...],
  "volatility_zscore": [0.5, 0.8, 1.2, 0.9, ...],
  "turnover_raw": [0.018, 0.022, 0.025, 0.019, ...],
  "turnover_zscore": [0.3, 0.7, 1.5, 0.6, ...],
  "resonance_strength": [0.0, 0.0, 0.0, 0.0, 0.65, ...],
  "resonance_state": ["NONE", "NONE", "NONE", "NONE", "ACTIVE", ...],
  "rsm_state_current": {                # 当前 RSM 状态（单值，非序列）
    "state": "ACTIVE",
    "duration": 3,
    "last_update": "2026-05-29"
  }
}
```

**LB 交互接口（RSM 状态持久化）**:
```
# run 启动时读取
def lb_read_state(symbol) -> dict:
    """返回: {"state": str, "duration": int, "last_update": str}
    首次运行/LB为空 → {"state": "NONE", "duration": 0, "last_update": None}
    """

# run 完成后写入
def lb_write_state(symbol, state: dict) -> bool:
    """写入当前 RSM 状态 + 持续天数
    幂等: 同一天覆盖写入
    """
```

---

## 5. 与现有系统的集成关系

### 5.1 与定时轮询系统的集成

```
现有定时轮询调度 (Cron Scheduler)
  │
  ├── morning_pipeline (Step1-5, 晨盘前)
  │     └── 共振框架 ← 复用 DataBridge 的数据管线
  │                    ← 共振信号写入 signals/signals/ 目录
  │                    ← 不修改 morning_pipeline 的调度逻辑
  │
  ├── midday_pipeline (Step1-5, 午盘后)
  │     └── 共振框架 ← 同上，复用数据 + 独立写入信号
  │
  └── 日内轮询 (每30min)
        └── 共振框架 ← SCL.run_once() 封装
                       ← DataBridge.get_latest() 检查是否有新数据
                       ← 有新数据才触发完整计算
```

**DataBridge 职责分离**:

DataBridge 在共振框架中承担两种职责，需明确区分：

| 职责 | 语义 | 使用场景 | 实现接口 |
|:----|:----|:---------|:--------|
| **信号推送** | 消息语义 — 推送当日新数据触发计算 | 日内/日终正常 run | `DataBridge.get_latest()` |
| **历史回放** | 数据查询语义 — 回放历史数据 | LB 初始化 / 回测 / 复盘 | `DataBridge.get_history(days=40)` |

**⚠️ 职责分离点**: 信号推送与历史回放使用不同的接口调用，不混入同一通道。信号推送通过 `get_latest()` 的增量检查机制，历史回放通过显式 `get_history()` 查询接口。实现时需保持两个接口的数据格式一致，但语义上分离。

### 5.2 与 IC 管线的集成

```
IC 管线 (A50 全成分股截面 IC)      共振框架 (A50 整体情绪-流动性)
     │                                    │
     │  (并行关系，相互独立)              │
     │                                    │
     ▼                                    ▼
┌────────────────┐            ┌────────────────────┐
│ IC_based_signal│            │ resonance_signal   │
│ (成分股级)      │            │ (市场整体级)        │
└───────┬────────┘            └─────────┬──────────┘
        │                               │
        └──────────┬───────────────────┘
                   ▼
        ┌────────────────────┐
        │ 信号整合层 (Phase 1)│
        │ 决策叠加/权重融合   │
        └────────────────────┘
```

### 5.3 共享组件清单

| 共享组件 | 所属系统 | 共振框架如何使用 | 冲突风险 |
|:---------|:---------|:----------------|:--------:|
| DataBridge | morning_pipeline | 复用数据获取接口 | 低 — 读操作不修改原数据 |
| data_contract.py | 数据层 | 复用 schema 校验 | 无 — 只读契约 |
| etl_normalizer.py | 数据层 | 复用标准化逻辑 | 无 — 只读函数 |
| source_registry.json | 数据层 | 复用数据源配置 | 无 — 只读配置 |
| signals/signals/ | 信号总线 | 写入共振信号 | 需命名空间隔离（前缀 `resonance_`） |
| Signal Protocol v1 | 信号层 | 输出格式兼容 | 无 — 结构相同 |
| Lookback Buffer | 共振框架独有 | 新增内存+文件缓存 | 无 — 新增目录 `cache/resonance/` |

**DataBridge 依赖契约**:
- **API 承诺**: DataBridge 对共振框架暴露的接口签名、返回值 schema 保持稳定
- **缓存承诺**: DataBridge 至少缓存 40 日历史数据（满足 20 日滚动窗 × 2 的 buffer 需求）
- **维度承诺**: DataBridge 返回 OHLCV + free_float 字段（DSV 辅源 Parkinson HV 依赖 high/low）
- **变更通知**: 当 morning_pipeline 有结构变更时，需同步验证共振框架的 DataBridge 适配
- **集成测试**: 验证 DataBridge 返回的数据字段对 DCM/LQM/DSV 模块的适配性

### 5.4 新增目录结构

```
resonance/                          # 新增: 共振框架根目录
├── cache/                          # 20日滚动缓存
│   ├── lookback_buffer_{symbol}.json
│   └── lookback_buffer_{symbol}.pkl
├── logs/                           # 运行日志
│   ├── resonance_{date}.json
│   └── veto_{date}.json
├── outputs/                        # 输出信号
│   └── {date}/
│       └── resonance_signal_{seq}.json
├── config.py                       # 配置（阈值、窗口、symbol）
│   ├── RESONANCE_MIN_STRENGTH = 0.6
│   ├── QUANTILE_THRESHOLD = 1.5
│   ├── LOOKBACK_DAYS = 20
│   └── BUFFER_DAYS = 40
├── data_bridge.py                  # DataBridge 适配
├── dcm.py                          # DCM 模块
├── lqm.py                          # LQM 模块
├── znm.py                          # ZNM 模块
├── rsm.py                          # RSM 模块
├── dsv.py                          # DSV 模块
├── gkv.py                          # GKV 模块
├── cpe.py                          # CPE 模块
├── sg.py                           # SG 模块
├── scl.py                          # SCL 模块
└── resonance_pipeline.py           # 主管线（组装各模块）
```

---

## 6. 否决制 / CONDITIONAL PASS 灰度层位置

### 6.1 否决制在框架中的精确位置

```
RSM (共振检测)            DSV (双源校验)
  │                          │
  │   (并行输入，互不依赖)    │
  └──────────┬───────────────┘
             ▼
┌──────────────────────────────────────────────────────────┐
│  GKV (门控&否决)                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  否决基线: strength < RESONANCE_MIN_STRENGTH       │  │  ← 【硬否决 #1】
│  │            OR duration < 2日                        │  │
│  │  数据否决: 原始数据有 gap/invalid                   │  │  ← 【硬否决 #2】
│  │  DSV否决: 双源校验不通过(非partial)                 │  │  ← 【硬否决 #3 — 墨萱红线】
│  └────────────────────────────────────────────────────┘  │
│                     │                                     │
│              ┌──────┴──────┐                              │
│              ▼              ▼                              │
│        VETO (终)         PASS                              │
│        写 .vetoed          │                               │
│        不生成信号           ▼                               │
└──────────────────────────────────────────────────────────┘
```

**墨萱红线**: DSV 双源校验 `passed == False AND partial == False` → 硬否决。不通过此门的信号绝不输出。

**否决不可绕过**: GKV 没有"强制执行"选项。否决是单向门。

### 6.2 CONDITIONAL PASS 在框架中的精确位置

```
GKV 通过
  │
  ▼
┌──────────────────────────────────────────────────────────┐
│  CPE (条件放行评估)                                        │
│  ┌────────────────────────────────────────────────────┐  │
│  │  判断条件: 连续5日共振强度 > RESONANCE_MIN_STRENGTH │  │
│  │           AND DSV 双源校验通过 (passed==True)?      │  │
│  ├────────────────────────────────────────────────────┤  │
│  │  YES ──────────────────────────→ CONDITIONAL_PASS │  │
│  │        position_cap = 0.5                           │  │
│  │        (仓位上限 ≤ 50%)                              │  │
│  │        reason = "持续高共振+双源通过 → 保守限仓"      │  │
│  ├────────────────────────────────────────────────────┤  │
│  │  NO (含 partial=True) ──────────→ FULL_PASS        │  │
│  │        position_cap = 1.0                           │  │
│  │        (正常仓位，仍受整体风控约束)                   │  │
│  │        reason = "条件放行条件未满足 → 正常仓位"       │  │
│  └────────────────────────────────────────────────────┘  │
│                                                           │
│  🟢 DSV partial=True 特殊规则:                            │
│     partial=True → CPE 自动 FULL_PASS                     │
│     (双源仅一源通过，不可触发 CONDITIONAL_PASS)            │
│                                                           │
│  ⏱ CONDITIONAL_PASS 信号生效窗口: T+1 开盘 30 分钟内有效  │
│                                                           │
│  📊 仓位上限受约束规则: position_cap = min(0.5, 风控上限) │
└──────────────────────────────────────────────────────────┘
```

### 6.3 否决制与 CONDITIONAL PASS 的层次关系

```
否决制（GKV）: 最外层硬门
  条件放行（CPE）: 内层灰度决策

否决是"能不能发信号"的二元判定
条件放行是"发了信号后怎么限制仓位"的灰度判定

GKV 不通过 → 不存在 CPE 评估环节
GKV 通过 → CPE 决定仓位上限

v2 修正: CONDITIONAL PASS 是"条件满足→受限"而非"条件满足→正常"
          触发条件越强 → 仓位越保守（辩论共识）
          触发条件不足 → 正常仓位
```

---

## 7. 调度层适配器设计

### 7.1 问题陈述

辩论结论确认：事件驱动 vs 定时轮询的"不兼容"限定在调度层，不影响底层计算引擎。

### 7.2 SCL 适配器接口

```python
class SchedulingAdapter(ABC):
    """调度层抽象基类 — 计算引擎零侵入"""

    @abstractmethod
    def run_once(self) -> dict:
        """单次执行共振判定全流程
        返回: resonance_signal dict 或 None(无新数据)
        """
        pass

    @abstractmethod
    def force_run(self, date: str = None) -> dict:
        """强制指定日期执行（回测/复盘用）
        参数:
          date: str — "YYYY-MM-DD" 格式
        返回: resonance_signal dict
        """
        pass

    def on_event(self, event: dict) -> dict:
        """事件驱动入口（Phase 1+ 支持）
        默认实现 = run_once()
        子类可重写为消息队列/Webhook 驱动
        """
        return self.run_once()
```

### 7.3 定时轮询实现 (PollingAdapter)

```python
class PollingAdapter(SchedulingAdapter):
    """定时轮询实现 — Phase 0 默认"""

    def __init__(self, interval_minutes=30, max_retries=1):
        self.interval = interval_minutes
        self.last_check = None
        self.max_retries = max_retries  # 重试保护

    def run_once(self):
        if not self._has_new_data():
            return None
        # 重试保护: 首次失败后重试1次，仍失败→静默跳过
        for attempt in range(self.max_retries + 1):
            try:
                result = resonance_pipeline.run()
                return self._to_signal(result)
            except Exception as e:
                if attempt < self.max_retries:
                    continue  # 重试
                # 最后一次失败: 记录日志，静默跳过
                logger.warning(f"PollingAdapter.run_once 失败(已重试{attempt}次): {e}")
                return None

    def _has_new_data(self) -> bool:
        """检查 DataBridge 是否有新数据"""
        try:
            latest = DataBridge.get_latest_date()
            return latest != self.last_check
        except Exception:
            return False  # 数据不可用→跳过
```

### 7.4 事件驱动实现 (EventAdapter) — Phase 1 预留

```python
class EventAdapter(SchedulingAdapter):
    """事件驱动实现 — Phase 1+"""

    def __init__(self, queue_url=None):
        self.queue = queue_url  # Redis Stream / Kafka

    def on_event(self, event: dict):
        """
        事件格式:
        {
            "type": "new_data_available" | "price_spike" | "manual_trigger",
            "payload": {...}
        }
        """
        if not self._validate_event(event):
            return None
        result = resonance_pipeline.run()
        return self._to_signal(result)
```

### 7.5 计算引擎零侵入保障

```python
# resonance_pipeline.py — 不被调度层感知

def run(config: dict) -> dict:
    """纯计算函数。不关心谁调用它、以什么频率调用。

    输入: config（包含 symbol, date, thresholds...）
    输出: resonance_signal dict

    幂等性说明:
    - 同一天多次调用: 结果相同（同一日输入数据不变，计算结果确定）
    - LB 写入: 采用"覆盖写入"策略（以 date 为键），不产生重复积累
    - 信号文件: 按 seq 递增命名，每次调用生成独立信号文件
    - 例外: 日内有新数据时（如 T+0 日内新成交数据到达），输出可能不同
      (这是预期行为——日内刷新计算结果)
    """
    # 1. 从 LB 恢复历史状态
    lookback = LookbackBuffer.read(config["symbol"])
    previous_rsm_state = lookback.get("rsm_state_current")

    # 2. 获取当日数据
    data = DataBridge.fetch(config["symbol"], config["date"])
    vol = DCM.compute(data)
    turn = LQM.compute(data)

    # 3. 标准化
    z_vol, z_turn = ZNM.normalize(vol, turn, lookback)

    # 4. 并行计算: RSM + DSV
    dsv = DSV.verify(z_vol, z_turn)              # DSV 校验（不依赖 RSM）
    resonance = RSM.detect(z_vol, z_turn,         # RSM 检测（不依赖 DSV）
                           previous_state=previous_rsm_state)

    # 5. 串行判定: GKV → CPE → SG
    gkv = GKV.gate(resonance, dsv)
    cpe = CPE.evaluate(resonance, dsv, gkv)
    signal = SG.generate(cpe)

    # 6. 持久化: 写入 LB
    LookbackBuffer.append(config["symbol"], {
        "date": config["date"],
        "z_vol": z_vol,
        "z_turn": z_turn,
        "resonance_state": resonance["state"],
        "resonance_strength": resonance["strength"],
    })
    LookbackBuffer.write_rsm_state(config["symbol"], {
        "state": resonance["state"],
        "duration": resonance["state_duration"],
        "last_update": config["date"],
    })

    return {"resonance": resonance, "gate": gkv, "conditional": cpe, "signal": signal}
```

**关键约束**: `resonance_pipeline.run()` 是纯函数，不含 scheduler context、threading、async。调度层只包装它，不修改其内部逻辑。

---

## 8. 轻架构考量与模块计数

### 8.1 模块计数

| 类型 | 模块名 | 代码行数估算 | 是否必需 Phase 0 |
|:----|:-------|:-----------:|:----------------:|
| 计算 | DCM | ~60 行 | ✅ 必需 |
| 计算 | LQM | ~40 行 | ✅ 必需 |
| 计算 | ZNM | ~50 行 | ✅ 必需 |
| 计算 | RSM | ~150 行 | ✅ 必需 |
| 计算 | DSV | ~100-120 行 | ✅ 必需 |
| 计算 | GKV | ~60 行 | ✅ 必需 |
| 计算 | CPE | ~70 行 | ✅ 必需 |
| 计算 | SG | ~50 行 | ✅ 必需 |
| 调度 | SCL (PollingAdapter) | ~100 行 | ✅ 必需 |
| 数据 | DataBridge 适配 | ~100 行 (复用现有接口) | ✅ 仅适配层 |
| 管线 | resonance_pipeline.py | ~70 行 | ✅ 必需 |
| **总计** | **11 文件(含配置)** | **~850 行** | — |

**对比**: 辩论中提到的"12-18 模块 vs 当前 3 模块"是在"全量共振+IC并行"场景下的估算。Phase 0 纯共振路径 = 8 计算模块 + 1 适配器 + 1 管线组装 = **10 个核心文件**。

### 8.2 轻架构保障措施

| 措施 | 说明 |
|:----|:------|
| 零外部依赖 | 不新增 pip 包，仅用 numpy/pandas/statistics 标准库 |
| 无状态计算 | `resonance_pipeline.run()` 为纯函数，所有状态由 Lookback Buffer 外部管理 |
| 文件级解耦 | 模块间通过标准 dict/DataFrame 传递数据，不共享内存状态 |
| `extras` 元数据 | 所有共振元数据随信号通过 `extras` 传递，不新增自定义数据结构 |
| 复用双源 | DSV 复用 ZNM 已有的数据。Phase 0 采用 **计算方法独立**（HV vs Parkinson HV 不同计算公式），Phase 1+ 升级为**数据来源独立**（引入独立数据源作为辅源） |
| 渐进式模块 | 模块内不可再拆子模块。一个模块 = 一个 .py 文件 = 一个类/函数 |

### 8.3 与 12-18 模块估算的关系

```
辩论中的 12-18 模块估算 = 共振(8) + IC截面(6~10) 的全量系统
Phase 0 纯共振 = 8 个计算+判定模块 (DCM/LQM/ZNM/RSM/DSV/GKV/CPE/SG)
               + 1 调度适配器 (SCL)
               + 1 管线组装
               = 10 核心文件

当 Phase 1 加入 IC 集成后，模块数自然增长到 12-18 区间。
```

---

## 9. 附录：Phase 0 → Phase 1 演进路线

| Phase | 时间 | 新增内容 | 模块变化 |
|:-----|:-----|:---------|:---------|
| **0** | T+0 | 纯共振框架 (HV+换手率) | 8 计算模块 + 1 适配器 |
| **0.5** | T+7 | IV 升级 (期权隐含波动率) | DCM 支持双模式 HV/IV |
| **0.5** | T+7 | 买卖价差作为流动性辅源 | LQM 扩展 |
| **0.5** | T+7 | 应急熔断 EMA 模块 | 新增 EMA 模块 (L3) |
| **1** | T+14 | IC 集成 (截面数据就绪后) | 新增 IC 计算管线 + 信号整合层 |
| **1.5** | T+21 | 事件驱动调度 | SCL 新增 EventAdapter |
| **1.5** | T+21 | 多标的支持 | DataBridge 支持批量 symbol |
| **1.5** | T+21 | 全独立双源 | DSV 升级为"数据来源独立"阶段 |

---

## 10. 变更日志（v1→v2）

| # | 来源 | 严重度 | 章节 | 变更描述 |
|:-:|:----|:-----:|:----:|:---------|
| 1 | C1 + X-A1 | 🔴 必须 | §1.2, §3.1, §3.4, §6.1 | RSM 与 DSV 统一声明为并行关系，修正依赖规则（RSM 不依赖 DSV），更新步骤链和数据流图 |
| 2 | O1 (Owner) | 🔴 必须 | §2.6, §6.2 | CPE 逻辑翻转：YES→CONDITIONAL_PASS（仓位受限），NO→FULL_PASS（正常仓位） |
| 3 | X-C1 | 🔴 必须 | §5.1, §5.3 | DataBridge 职责分离：信号推送 vs 历史回放，增加依赖契约声明 |
| 4 | C2 | 🟡 建议 | §3.1 | 补充 Step 0.5A（LB 读取）和 Step 9.5A/B（LB 更新） |
| 5 | C3 + X-B1/X-B2 | 🟡 建议 | §2.3, §3.1, §4.4 | RSM 状态机增加"读→判→写"闭环设计，状态过期策略，LB 交互接口 |
| 6 | A2/B1 | 🟡 建议 | §2.3 | RSM 标注二层内部结构：`_compute_strength()` + `_transition_state()` |
| 7 | A1 | 🟡 建议 | §1.2 | SCL 措辞修正：从"不依赖"改为"不嵌入业务逻辑，仅通过 pipeline.run() 统一接口调用" |
| 8 | D1 | 🟢 低 | §2.5, §2.6 | 提取 `RESONANCE_MIN_STRENGTH = 0.6` 全局常量，GKV 和 CPE 统一引用 |
| 9 | D2 | 🟢 低 | §2.6, §6.2 | DSV partial=True → CPE 自动 FULL_PASS，不可触发 CONDITIONAL_PASS |
| 10 | B2 | 🟢 低 | §2.4 | DSV Spearman 增加 guard clause: `if std == 0: return {"passed": False, "score": 0.0}` |
| 11 | E1 | 🟢 低 | §7.3 | PollingAdapter 增加 `max_retries=1, fallback=skip_silently` 韧性机制 |
| 12 | E2 | 🟢 低 | §7.2 | `force_run(date: str)` 补充格式说明："YYYY-MM-DD" |
| 13 | O2 (Owner) | 🟡 建议 | §2.4, §8.2 | 明确 Phase 0 双源定位为"计算方法独立"，Phase 1+ 升级为"数据来源独立" |
| 14 | O3 (Owner) | 🟢 低 | §7.5 | `pipeline.run()` 增加幂等性说明：同一天覆盖写入，按 seq 命名不重复 |
| 15 | X-C2 | 🟢 低 | §2.4 | DSV 辅源可用性检测：DataBridge 增加 `available_dimensions` 字段声明 |
| 16 | X-D1 | 🟢 低 | §2.6, §6.2 | CONDITIONAL_PASS 补充信号生效窗口、仓位上限受约束规则 |
| 17 | X-E1 | 🟢 低 | §8.1 | DSV 代码行数估算更新 80→100-120，RSM 更新 120→150（含状态机逻辑） |

---

## 文件记录

| 字段 | 值 |
|:----|:----|
| author | moheng |
| created_time | 2026-05-29T09:15:00+08:00 |
| version | v2.0 |
| based_on | 辩论总结_会签_v1.0.md / ARCH001_v1 |
| reviewer_feedback | moxuan(2026-05-29T08:45) / xuanzhi(2026-05-29T08:48) / owner(2026-05-29T08:51) |
| status | DESIGN_FIXED |
| fix_history | v1→v2: 17项修复（3必须+4建议+10可选），参见 §10 变更日志 |
