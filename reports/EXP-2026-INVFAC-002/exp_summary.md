# EXP-2026-INVFAC-002 回测结果摘要
> completed: 2026-05-25T17:59:43+08:00
## Bootstrap 检验汇总

| 因子 | 状态 | 持有期 | IC | p值 | 显著 | FDR_BH |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| TrendQuality | high_vol | 5d | -0.0087 | 0.2652 | NS | BH_NS |
| TrendQuality | high_vol | 10d | -0.0124 | 0.1059 | NS | BH_NS |
| TrendQuality | high_vol | 20d | -0.0202 | 0.0070 | SIG | BH_SIG |
| l_str_kdj_k | mid_vol | 5d | -0.0051 | 0.9536 | NS | BH_NS |
| l_str_kdj_k | mid_vol | 10d | 0.0307 | 0.7258 | NS | BH_NS |
| l_str_kdj_k | mid_vol | 20d | -0.0823 | 0.3447 | NS | BH_NS |
| l_str_kdj_k | high_vol | 5d | 0.0131 | 0.0931 | NS | BH_NS |
| l_str_kdj_k | high_vol | 10d | 0.0197 | 0.0101 | SIG | BH_SIG |
| l_str_kdj_k | high_vol | 20d | -0.0081 | 0.2902 | NS | BH_NS |
| l_vol_rsi_std | high_vol | 5d | 0.0148 | 0.0562 | NS | BH_NS |
| l_vol_rsi_std | high_vol | 10d | 0.0130 | 0.0928 | NS | BH_NS |
| l_vol_rsi_std | high_vol | 20d | 0.0478 | 0.0000 | SIG | BH_SIG |

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
| TrendQuality | high_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | high_vol | 20d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | low_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_str_kdj_k | low_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_str_kdj_k | low_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_str_kdj_k | mid_vol | 5d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | mid_vol | 10d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | mid_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | high_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | high_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | high_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | low_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | low_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | low_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | mid_vol | 5d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | mid_vol | 10d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | mid_vol | 20d | FAIL | FAIL | FAIL | FAIL | FAIL |
| l_vol_rsi_std | high_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| l_vol_rsi_std | high_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| l_vol_rsi_std | high_vol | 20d | PASS | PASS | PASS | PASS | PASS |
