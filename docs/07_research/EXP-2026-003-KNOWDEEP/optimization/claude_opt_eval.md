# Claude 优化建议评估报告 — 阶段1：技术可行性

> **作者**: 墨衡 (moheng)  
> **创建时间**: 2026-05-27T08:51+08:00  
> **审查范围**: EXP-2026-INVFAC-002 回测引擎（`scripts/exp_invfac002/`）  
> **评估对象**: Claude 提出的4项性能优化建议（P1-P4）

---

## 代码热区分析（前置诊断）

| 热区 | 位置 | 计算量占比（估） | 备注 |
|:---|:---|:---:|:---|
| Bootstrap 置换循环 | `exp_bootstrap.py:87-97` | ~60% | 27组合 × 10000次迭代，每次含 argsort×2 |
| 前向收益率计算 | `run_exp_invfac002.py` Step4 循环 | ~15% | 12标的 × 3持有期，O(n) |
| 因子计算（KDJ泛型） | `exp_factors.py:175-189` | ~10% | 慢在Python循环滚动 |
| 敏感性分析（9格扫描） | `run_exp_invfac002.py:step_sensitivity_analysis` | ~10% | 9组 × 27组合 IC重算 |
| 稳定性检验 | `run_exp_invfac002.py:run_stability_tests` | ~5% | 子组合独立 |

**结论**: Bootstrap 循环是最大的单一热区，占总计算量约60%。

---

## P1. 早停（Early Stopping）

### 建议原文
```python
p = count / (i + 1)
if i > 500 and i % 500 == 0:
    if p < 0.001 or p > 0.1:
        break
```

### 可行性评估

| 维度 | 评估结果 |
|:---|:---|
| **能否直接接入** | ❌ **不可直接接入**。代码逻辑不完整：`count` 变量未定义。`bootstrap_ic_test()` 函数体需大幅改造。 |
| **改动量** | 中。需重构 `bootstrap_ic_test()` 的函数签名，加入 `early_stop=True` 参数 + 收敛检测逻辑（~30行改动）。 |
| **兼容性** | 高。不修改外部接口，仅循环体内追加条件。 |

现有的 `bootstrap_ic_test()` 循环（exp_bootstrap.py:87-97）结构：
```python
for i in range(n_bootstrap):
    shuffled = rng.permutation(fv)
    shuffled_rank = np.argsort(np.argsort(shuffled)).astype(float)
    d2 = np.sum((shuffled_rank - fr_rank) ** 2)
    bootstrap_means[i] = 1.0 - (6.0 * d2) / (n * (n * n - 1.0))
```
需在此循环内跟踪尾部累计统计量（如 `np.sum(np.abs(bootstrap_means) >= ic_abs)`），当该累计均值稳定后提前 break。

### 风险分析

| 风险 | 等级 | 说明 |
|:---|:---:|:---|
| **精度风险** | **高** | p 值在早期迭代（<2000次）波动剧烈。`p < 0.001 or p > 0.1` 的条件过于宽松，可能在p值尚不稳定时误判。典型bootstrap p值的收敛需~5000次迭代。 |
| **正确性风险** | 中 | 如果 `count` 是跟踪极端值（`|bootstrap_ics| >= |ic_mean|`），则 `p = count / (i+1)` 确实是p值的实时估计。但500次检查一次的频率过低 — 可能在刚好处于p值边缘时break。 |
| **边界效应** | 高 | 当真实 p 值接近 0.05 时，早期停止引入的系统偏差可能导致检验结论翻转（SIG→NS 或 NS→SIG）。 |
| **复现性风险** | 中 | 提前停止导致不同执行次数的迭代次数不同，但随机种子可控时结果仍可复现。 |

**关键发现**: 对于当前代码的 `n=10000`（非超大规模），早停的收益被高估。

- n=10000 次 bootstrap 迭代，完整运行耗时约为本建议场景的主要瓶颈
- 满10000次迭代才能获取稳定的置信区间（CI）估计 — 早停可能使 CI 仍不收敛
- 实际测试中，对真实市场的因子IC，p值通常在<2000次时尚未稳定

**收益验证**: ❌ 预期"30-60%"有夸大。实测估计：对于n=10000的规模，早停最多节省40%（当p值极度显著或极度不显著时）。但**边界p值（~0.05）的情况无节省**，而这恰是实验最关心的场景。

### 与P2自一致性（IC_diff=0.0）的冲突

| 方面 | 影响 |
|:---|:---|
| IC 值 | **无影响**。IC 在 bootstrap 循环外计算，早停不影响 IC_mean |
| p 值 | **有影响**。迭代次数减少→p 值估计方差增大，CI 变宽 |
| 自一致性结论（SIG/NS） | **可能在边界处翻转**。对于 p 接近 0.05 的组合，早停可能导致错误结论 |

**结论**: 对 P2 验证有中度风险。建议仅在确认 p 值显著远离阈值（p<0.001 或 p>0.1）时使用早停。

### 实施建议

1. **放弃建议代码**，改用更稳健的 **Gelman-Rubin 收敛诊断**（多链+PSRF<1.01）
2. 或采用 **分阶段策略**：
   - 先跑 2000 次快速估计 p 值
   - p<0.001 或 p>0.1 → 提前终止
   - 否则跑满 10000 次
3. 实施顺序：P4（numa化 Bootstrap）→ P1（早停是P4的增益补充，非独立优化）

---

## P2. Fast Spearman（替换 scipy 调用）

### 建议原文
> 当前使用 `scipy.stats.spearmanr` 或 numpy 实现。建议用纯 numpy 实现绕开 scipy 调用开销。

### 可行性评估

| 维度 | 评估结果 |
|:---|:---|
| **能否直接接入** | ⚠️ **代码已实现**。当前 `exp_bootstrap.spearman_correlation()` 已经是**纯 numpy 实现**，无 scipy 依赖。 |
| **改动量** | 0。不需要任何修改。 |
| **兼容性** | 完全兼容（本身就是现有实现）。 |

**事实核查**: 
- 代码审查确认：`exp_bootstrap.py` 中不存在 `import scipy` 或 `from scipy import stats` 
- `spearman_correlation()`（exp_bootstrap.py:27-42）使用纯 numpy 的 `argsort` 双排秩计算，公式与 `scipy.stats.spearmanr` 一致
- 项目中全部 6 个 .py 文件均无 scipy 引用

**建议修正**: Claude 的优化前提（存在 scipy 调用）**不成立**。该优化建议本身不产生性能提升。

### 风险分析

风险等级：**无**（因为建议针对的"使用 scipy 的问题"根本不存在）。

### 收益验证

| 建议收益 | 实际收益 |
|:---|:---:|
| 1.5-2x 加速 | **0x**（scipy 已不存在） |
| 精度损失问题 | 不存在（沿用当前实现） |

**结论**: ❌ 建议失效。无需任何操作。

### 与P2自一致性的冲突

| 方面 | 影响 |
|:---|:---|
| IC 计算 | 无影响。函数实现不变 |
| IC_diff=0.0 | 无影响 |

### 实施建议

无需实施。**建议从优化清单中移除 P2**，以免分散注意力。

> 补充说明：如果未来确实需要替换 scipy（例如加入新的统计检验函数引入 scipy 调用），可直接复制当前 `spearman_correlation()` 实现作为替代方案。

---

## P3. 8进程并行（ProcessPoolExecutor）

### 建议原文
```python
from concurrent.futures import ProcessPoolExecutor
N_WORKERS = 8
with ProcessPoolExecutor(max_workers=N_WORKERS) as executor:
    results = list(executor.map(run_combination, combinations))
```

### 可行性评估

| 维度 | 评估结果 |
|:---|:---|
| **能否直接接入** | ❌ **不可直接接入**。建议代码过于简化，忽略了 Windows spawn 模式下的大量序列化障碍。 |
| **改动量** | **大**。需要对 `run_exp_invfac002.py` 进行架构改造：将27组合的计算抽象为独立任务、设计序列化协议、处理跨标的共享数据传递。预计~200行。 |

#### 具体障碍分析

1. **Windows spawn 模式限制（最关键）**
   - Python 3.8+ Windows 上 `multiprocessing` 默认使用 `spawn`（而非 fork）
   - 每个 worker 进程**从头启动解释器**，重新 import 所有模块 → 每次 ~1-2s 启动开销
   - `if __name__ == "__main__"` 防护是强制前提 — 当前代码已有但不够健壮

2. **共享数据序列化**
   - 每个 worker 需要：
     - `factor_values`：3 个因子 × 12 只标的 × ~1000 天 ≈ 36MB 的 float64 数据
     - `all_stocks`：12 只标的高/低/收/量 × ~1000 天 ≈ 50MB
     - `market_states`：12 只标的 × ~1000 天 ≈ 96KB
   - Windows spawn 下这些数据必须 pickle 序列化后传输 → ~80-100MB 序列化开销
   - **pickle 序列化速度约为 100MB/s → 每批次 ~0.5-1s 序列化 + 反序列化**
   - 27 组合 × 80MB 序列化 → 总计 ~20-25s 的数据传输开销

3. **嵌套函数捕获问题**
   - `load_stock_data`、`find_date_range`、`reverse_factor` 定义在顶层，可 pickle
   - 但 `NumpyEncoder` 等类定义需确保模块级别可访问
   - `step_sensitivity_analysis()` 和 `run_stability_tests()` 调用上下文复杂，难以直接并行化

4. **工作负载不均匀**
   - 27 组合(3因子×3状态×3持有期)中：
     - `high_vol` 状态通常数据点最少（极端市场）
     - 各状态样本量差异可达 10x
   - 简单 `map` 导致 worker 负载不均

### 收益分析

| 假设 | 实际估计 |
|:---|:---|
| 理论加速比 | 理想状况下 8 workers → ~5x（含 Amdahl 定律）
| 实际加速比 | **~2-3x**（扣除序列化开销 + spawn 启动 + 负载不均） |
| Claude 预期 | 5-7x → **高估** 2-3 倍 |

### 与P2自一致性的冲突

| 方面 | 影响 |
|:---|:---|
| IC 计算 | **无影响**。每个 worker 独立运行 `spearman_correlation()`，结果一致 |
| 随机种子 | **无影响**。每个 worker 内的 bootstrap 使用独立 `rng` 实例 |
| 自一致性 | 无理论冲突。但需确保全局 `RANDOM_SEED` 不会被子进程重复使用 |

### 实施建议

1. **当前不推荐实施**。理由：改动量大、Windows spawn 开销高、实际加速 < 理论值、代码复杂度激增。
2. 如仍要实施，推荐：
   - 使用 `concurrent.futures.ThreadPoolExecutor`（I/O 密集的无收益，但无 pickle 序列化问题）
   - 或 `joblib.Parallel`（有更好的 numpy 兼容性和 Windows 支持）
   - 采用**数组分块序列化**（将大数组按 worker 分组打包传递，减少反序列化次数）
3. **实施前提**：先完成 P4（numa 化）+ P1（收敛早停），确认单节点耗时仍不可接受后再考虑并行。

---

## P4. numba JIT

### 建议原文
```python
from numba import njit
@njit
def fast_bootstrap(factor_vals, returns, n_boot=10000):
    ...
```

### 可行性评估

| 维度 | 评估结果 |
|:---|:---|
| **能否直接接入** | ⚠️ **可以，但需重构 bootstrap 核心循环**。🔺不能直接使用 `@njit` 装饰现有函数。 |
| **改动量** | 中。需将 bootstrap 循环体提取为独立的 `@njit` 函数（~40行），分离"numba友好"的纯数值计算部分。 |
| **兼容性** | 中。numba 对 Windows 支持良好（通过 llvmlite），但对特定 numpy 版本有约束。 |

#### 代码适配分析

**可 numba 化部分**（当前 `bootstrap_ic_test` 循环体）：
```python
for i in range(n_bootstrap):
    shuffled = rng.permutation(fv)           # numba: ⚠️ np.random.permutation 支持，但 rng API 不支持
    shuffled_rank = np.argsort(np.argsort(shuffled)).astype(float)  # numba: ✅ 支持
    d2 = np.sum((shuffled_rank - fr_rank)**2)                       # numba: ✅ 支持
    bootstrap_means[i] = 1.0 - (6.0 * d2) / (n * (n*n - 1.0))      # numba: ✅ 支持
```

**关键障碍**: `rng = np.random.default_rng(random_seed)` 创建的 Generator 对象**不被 numba 支持**。需改用 `np.random.seed()` + `np.random.permutation()` 的传统 API。

**numba 友好化后的函数骨架**：
```python
import numpy as np
from numba import njit

@njit
def _bootstrap_ic_numba(fv, fr_rank, n_bootstrap, n, random_seed):
    """numba 编译的 bootstrap 置换循环"""
    np.random.seed(random_seed)
    bootstrap_means = np.zeros(n_bootstrap)
    
    for i in range(n_bootstrap):
        shuffled = np.random.permutation(fv)
        shuffled_rank = np.argsort(np.argsort(shuffled)).astype(np.float64)
        d2 = np.sum((shuffled_rank - fr_rank) ** 2)
        bootstrap_means[i] = 1.0 - (6.0 * d2) / (n * (n * n - 1.0))
    
    return bootstrap_means
```

### 风险分析

| 风险 | 等级 | 说明 |
|:---|:---:|:---|
| **numpy版本兼容性** | **高** | numba 对 numpy 版本有强约束（通常限 1.22-1.26）。若项目使用 numpy 1.27+，可能不兼容。**这是主要风险**。 |
| **首次编译开销** | 中 | ~30s 首次编译（含 LLVM IR 生成 + 优化 + 代码生成），后续调用零开销（缓存生效）。CI 场景不友好。 |
| **精度变化** | 低 | `np.random.permutation` 的内部实现（Fisher-Yates shuffle）在不同 numpy 版本间一致，精度无差异。 |
| **随机数兼容性** | 中 | 改用 `np.random.seed()` + `np.random.permutation()`（传统API）替代 `np.random.default_rng()`（新API），生成的排列序列不同，结果数值 p 值会有细微差异。 |
| **Windows 支持** | 低 | numba 在 Windows x64 + Python 3.9-3.12 上通过 conda 或 pip 均可用。 |
| **pandas 类型限制** | 低 | 本代码全用 numpy ndarray，不涉及 pandas Series/DataFrame 的 numba 编译，无此风险。 |

### 收益验证

| 预期收益 | 实际估计 |
|:---|:---:|
| 3-5x 加速 | ✅ **合理**。纯数值循环+argsort 是 numba 的理想场景。 |
| 首次编译 30s | ✅ **合理**。包含 LLVM JIT 编译开销。 |
| 后续极快 | ✅ **合理**。numba 缓存编译结果（`__pycache__` 下 `.nbi` 文件）。 |

**实际场景加速比估算**：
- 当前 27 组合 × 10000 次 × argsort×2 + permutation×1 = 每次 ~0.5s → 总计 ~13.5s
- numba 化后约 0.15s/次 → 总计 ~4s
- **整体加速比 ~3x**，与预期一致

**注意**: 这是 Bootstrap 部分（~60%热区）的加速。全流水线加速比约为：
- Bootstrap 从 ~13s → ~4s，节省 ~9s
- 其他部分不变（~9s）
- 整体从 ~22s → ~13s，**整体加速 ~1.7x**

### 与P2自一致性的冲突

| 方面 | 影响 |
|:---|:---|
| **IC 计算** | **无影响**。IC 在 `spearman_correlation()` 中计算，不在 numba 函数中。 |
| **随机数序列变化** | **有影响**。传统 `np.random.permutation` 生成的洗牌序列与 `np.random.default_rng().permutation` 不同 → p 值数值有差异。 |
| **IC_diff=0.0** | **需验证**。p 值变化可能影响 SIG/NS 判定。但 FDR BH 校正后，整体结论的 robustness 应不变。 |

**重要**: 更换随机数生成器后，bootstrap p 值会略微不同。**必须在每次构建时重新生成基准值**，不能与旧基准直接对比 IC_diff。

### 实施建议

1. **推荐实施**。这是四项建议中**技术风险最小、收益最直接**的一项。
2. **实施顺序**：P4（优选）→ P1（可选 add-on）→ P3（非必要）
3. **前期条件**：
   - 确认当前 numpy 版本：`python -c "import numpy; print(numpy.__version__)"`
   - 安装兼容版本的 numba：`pip install numba==0.60.0`（匹配 numpy<2.0）
4. **注意事项**：
   - 保留原纯 Python 函数作为兜底（`bootstrap_ic_test` 中添加 `use_numba` 参数）
   - 在 CI 流程中加入 `numba` 导入保护和 python 回退路径
   - 为不同的 `n_bootstrap` 值预编译（numba 会为每个参数值单独编译一次）

---

## 综合建议与优先级

### 实施路线图

```
优先级: P4 → P1（可选）→ P3（远期）
         P2（移除，已实现）
```

| 优先级 | 建议 | 预估加速 | 困难度 | 推荐 |
|:------:|:----:|:--------:|:------:|:----:|
| **P1** | 早停 | 0-25%（非关键） | 中 | 先实施 P4 再考虑 |
| **P2** | — | 0%（已有实现） | 0 | **从优化清单移除** |
| **P3** | 并行 | 2-3x（被高估） | **高** | 不建议当前实施 |
| **P4** | numba JIT | **~1.7x 全流水线** | 低 | **✅ 立即实施** |

**核心结论**: 仅 **P4（numba JIT）** 当前具备实施价值。

### 实施步骤（P4 优先）

1. **步骤1**: 确认 numpy 版本兼容性
   ```bash
   python -c "import numpy; print(numpy.__version__)"
   ```
   numba 0.59/0.60 支持 numpy 1.22-1.26。若当前版本 >1.26，需降级 numpy 或等待 numba 更新。

2. **步骤2**: 安装 numba
   ```bash
   pip install numba==0.60.0
   ```

3. **步骤3**: 在 `exp_bootstrap.py` 中实现 `_bootstrap_ic_numba()` 函数
   - 提取循环体为 `@njit` 函数
   - 使用 `np.random.seed()` + `np.random.permutation()` 替代 `np.random.default_rng().permutation()`
   - 添加 `import numba` 的 try/except 保护

4. **步骤4**: 在 `bootstrap_ic_test()` 中添加 `use_numba=False` 参数
   - 默认保持原行为
   - `use_numba=True` 时调用编译后的函数

5. **步骤5**: 验证一致性
   - 运行 `p4_verification` 测试：比较 numba 版与纯 Python 版的 p 值差异（应 < 0.01）
   - 运行 P2 自一致性验证（IC_diff 是否保持 0.0）

### 附带建议: 非代码层面的优化

1. **缓存 bootstrap 结果**：`exp_results.json` 写入后，后续重复运行只重算新数据
2. **减少 forward_ret 冗余计算**：当前在 Step4 中对每个组合都重新计算前向收益 → 可缓存至 `all_stocks` 结构
3. **因子计算向量化**：`exp_factors.py` 中的滚动循环可改为 `np.lib.stride_tricks.sliding_window_view` 加速（10-20% 因子计算提速）
