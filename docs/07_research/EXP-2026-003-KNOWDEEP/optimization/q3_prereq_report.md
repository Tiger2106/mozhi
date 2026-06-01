# EXP-2026-003-KNOWDEEP: Q3前置条件完成报告（第一阶段）

> **author**: 墨衡 (moheng)  
> **created**: 2026-05-27T12:00+08:00  
> **git commit**: `bc5f464`  
> **git tag**: `exp003-q2-v1`

---

## 全部4项前置条件完成状态

| # | 项目 | 状态 | 说明 |
|:-:|:----|:----:|:-----|
| 1 | Q2代码 Git commit + Tag | ✅ **完成** | `exp003-q2-v1` tagged |
| 2 | C1-RWC 权重灵敏度分析 (±20%) | ✅ **完成** | 方向一致性和IC>0均保持 |
| 3 | C2-RFS 低信噪比标注逻辑 | ✅ **完成** | 新增 `signal_quality` 字段 |
| 4 | 随机种子锁定 (P2项) | ✅ **完成** | `np.random.RandomState` 替换 `default_rng` |

---

## 1. Q2代码 Git commit + Tag

**提交文件：** 9 files changed, +2223/-12

| 文件 | 说明 | 状态 |
|:----|:----|:----:|
| `scripts/exp_invfac002/exp_bootstrap.py` | 含 `apply_verdict_degradation` + 随机种子锁定 | 已修改 |
| `scripts/exp_invfac002/data_qc_check.py` | Q2数据质量检查 | 已修改 |
| `scripts/exp003_knowdeep/self_check.py` | 自检清单校验模块（新建） | 新增 |
| `scripts/exp003_knowdeep/run_exp003_q1.py` | Q1跨窗口鲁棒性验证主脚本（含超时自检集成） | 新增 |
| `scripts/exp003_knowdeep/run_exp003_q2.py` | Q2组合信号分析（含C2-RFS低信噪比标注） | 新增 |
| `scripts/exp003_knowdeep/test_p1_fixes.py` | P1修复验证测试（新建） | 新增 |
| `scripts/exp003_knowdeep/c1_rwc_sensitivity.py` | C1-RWC权重灵敏度分析（新建） | 新增 |
| `scripts/exp003_knowdeep/verify_seed.py` | 随机种子验证（新建） | 新增 |
| `scripts/exp003_knowdeep/verify_c2_snr.py` | C2-RFS低信噪比验证（新建） | 新增 |

**Tag:** `exp003-q2-v1`

---

## 2. C1-RWC 权重灵敏度分析 (±20%)

**基准权重:** HV=0.5, MV=0.3, LV=0.2

### 扰动组合 (共8种)

| 扰动 | HV | MV | LV | Train IC(20d) | Val IC(20d) | DirCons |
|:----|:--:|:--:|:--:|:------------:|:----------:|:------:|
| 基准 | 0.5 | 0.3 | 0.2 | 0.1028 | 0.1384 | — |
| HV-20% | 0.4 | 0.3 | 0.2 | 0.1070 | 0.1379 | ✅ |
| HV+20% | 0.6 | 0.3 | 0.2 | 0.0991 | 0.1377 | ✅ |
| MV-20% | 0.5 | 0.24 | 0.2 | 0.0981 | 0.1343 | ✅ |
| MV+20% | 0.5 | 0.36 | 0.2 | 0.1040 | 0.1379 | ✅ |
| LV-20% | 0.5 | 0.3 | 0.16 | 0.1001 | 0.1377 | ✅ |
| LV+20% | 0.5 | 0.3 | 0.24 | 0.1032 | 0.1361 | ✅ |

**结论:** 方向一致性保持率 Train 8/8, Val 8/8; IC>0 保持率 8/8  
**复杂度判定:** C1-RWC 权重在 ±20% 范围内稳健 → **C1≈C3**（权重选择不关键）

### IC变化范围

| 持有期 | Train IC变化 | Val IC变化 |
|:-----:|:----------:|:---------:|
| p5d | [0.0934, 0.0993] | [0.1170, 0.1232] |
| p10d | [0.0997, 0.1066] | [0.1227, 0.1289] |
| p20d | [0.0981, 0.1070] | [0.1343, 0.1384] |

**输出文件:** `reports/EXP-2026-003-KNOWDEEP/optimization/c1_rwc_sensitivity.json`

---

## 3. C2-RFS 低信噪比标注逻辑

### 修改内容

在 `scripts/exp003_knowdeep/run_exp003_q2.py` 的 `compute_decay()` 函数中新增了低信噪比自动标注逻辑：

```python
# 当训练期|IC|<0.01时，自动标注[低信噪比]，不影响现有verdict逻辑
snr_note = ""
if enable_snr_annotation and ti_m is not None and abs(ti_m) < 0.01:
    snr_note = "[低信噪比]"
```

### 输出字段

每个 `decay[period]` 条目新增 `signal_quality` 字段：
- `"[低信噪比]"` — 当训练期 |IC| < 0.01
- `null` — 正常信号质量

### 验证结果

| 测试用例 | Train IC | 触发标注 | Verdict不受影响 |
|:--------|:--------:|:--------:|:--------------:|
| C2-RFS p5d | 0.0008 | ✅ [低信噪比] | ✅ PASS不变 |
| C2-RFS p10d | 0.0050 | ✅ [低信噪比] | ✅ PASS不变 |
| C2-RFS p20d | 0.0200 | ❌ 不触发 | ✅ PASS不变 |
| 正常IC | 0.05 | ❌ 不触发 | ✅ PASS不变 |

**验证脚本:** `scripts/exp003_knowdeep/verify_c2_snr.py`

---

## 4. 随机种子锁定 (P2项)

### 修改内容

在 `scripts/exp_invfac002/exp_bootstrap.py` 的 `bootstrap_ic_test()` 函数中：

**修改前:**
```python
rng = np.random.default_rng(random_seed)
```

**修改后:**
```python
np.random.seed(random_seed)
rng = np.random.RandomState(random_seed)
```

### 改动要点

1. **`np.random.seed(random_seed)`** — 在bootstrap入口处锁定全局随机种子
2. **`np.random.RandomState`** — 替代 `numpy.random.Generator` (default_rng)，确保与旧版numpy兼容
3. **`rng.permutation()`** — 接口兼容，无需修改调用代码

### 验证结果

- ✅ 相同随机种子 (seed=42) 产生完全一致的 p-value 和 IC
- ✅ 不同随机种子 (seed=99) 产生不同结果
- ✅ `np.random.default_rng` 已完全移除
- ✅ 与现有所有调用代码兼容

**验证脚本:** `scripts/exp003_knowdeep/verify_seed.py`

---

## 附：玄知技术把关5项条件矩阵

| 条件 | 状态 | 关联文件 |
|:----|:----:|:--------|
| (1) Q1代码版本锁定 | ⏳ Q3同步处理 | `run_exp003_q1.py` → git已纳管 |
| (2) Q2代码版本锁定 | ✅ 本次完成 | `run_exp003_q2.py` → git tag `exp003-q2-v1` |
| (3) C1-RWC权重灵敏度 | ✅ 本次完成 | `c1_rwc_sensitivity.py` + `c1_rwc_sensitivity.json` |
| (4) C2-RFS低信噪比标注 | ✅ 本次完成 | `run_exp003_q2.py` compute_decay() |
| (5) 随机种子锁P2 | ✅ 本次完成 | `exp_bootstrap.py` bootstrap_ic_test() |

---

## 代码版本与环境信息

| 条目 | 值 |
|:----|:----|
| Git commit hash | `bc5f464` |
| Git tag | `exp003-q2-v1` |
| Git branch | master |
| OS | Windows_NT 10.0.26200 (x64) |
| Python | 3.14 |
| numpy | 2.x |
| sqlite3 | bundled |

---

*报告结束*
