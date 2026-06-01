# EXP-2026-002-INVFAC 回测结果摘要
> completed: 2026-05-26T11:01:42+08:00
> version_tag: 0bec5f6
> run_timestamp: 2026-05-26T10:51:07+08:00
## Bootstrap 检验汇总

| 因子 | 状态 | 持有期 | IC | p值 | 显著 | FDR_BH |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| TrendQuality | high_vol | 5d | -0.0098 | 0.1856 | NS | BH_NS |
| TrendQuality | high_vol | 10d | -0.0160 | 0.0316 | SIG | BH_NS |
| TrendQuality | high_vol | 20d | -0.0288 | 0.0001 | SIG | BH_SIG |
| l_str_kdj_k | mid_vol | 5d | -0.1063 | 0.2027 | NS | BH_NS |
| l_str_kdj_k | mid_vol | 10d | -0.0738 | 0.3754 | NS | BH_NS |
| l_str_kdj_k | mid_vol | 20d | -0.1121 | 0.1789 | NS | BH_NS |
| l_str_kdj_k | high_vol | 5d | 0.0134 | 0.0702 | NS | BH_NS |
| l_str_kdj_k | high_vol | 10d | 0.0139 | 0.0628 | NS | BH_NS |
| l_str_kdj_k | high_vol | 20d | -0.0192 | 0.0086 | SIG | BH_SIG |
| l_vol_rsi_std | high_vol | 5d | 0.0146 | 0.0479 | SIG | BH_NS |
| l_vol_rsi_std | high_vol | 10d | 0.0141 | 0.0578 | NS | BH_NS |
| l_vol_rsi_std | high_vol | 20d | 0.0424 | 0.0000 | SIG | BH_SIG |

## L3 稳定性检验汇总

| 因子 | 状态 | 持有期 | 时间切片 | 滚动窗口 | 标的交叉 | OOS | L3 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| TrendQuality | low_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| TrendQuality | low_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| TrendQuality | low_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| TrendQuality | mid_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| TrendQuality | mid_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| TrendQuality | mid_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| TrendQuality | high_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | high_vol | 10d | PASS | PASS | FAIL | PASS | PASS |
| TrendQuality | high_vol | 20d | PASS | PASS | FAIL | PASS | PASS |
| l_str_kdj_k | low_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_str_kdj_k | low_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_str_kdj_k | low_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_str_kdj_k | mid_vol | 5d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | mid_vol | 10d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | mid_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | high_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | high_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | high_vol | 20d | PASS | PASS | PASS | PASS | PASS |
| l_vol_rsi_std | low_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | low_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | low_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | mid_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | mid_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | mid_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | high_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| l_vol_rsi_std | high_vol | 10d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | high_vol | 20d | PASS | PASS | PASS | PASS | PASS |
