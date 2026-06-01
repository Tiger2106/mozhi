# EXP-2026-INVFAC-002 回测结果摘要
> completed: 2026-05-27T21:56:05+08:00
> version_tag: bc5f464
> run_timestamp: 2026-05-27T21:40:20+08:00
## Bootstrap 检验汇总

| 因子 | 状态 | 持有期 | IC | p值 | 显著 | FDR_BH |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| TrendQuality | low_vol | 5d | -0.0304 | 0.0001 | SIG | BH_SIG |
| TrendQuality | low_vol | 10d | -0.0543 | 0.0000 | SIG | BH_SIG |
| TrendQuality | low_vol | 20d | -0.0519 | 0.0000 | SIG | BH_SIG |
| TrendQuality | mid_vol | 5d | -0.0026 | 0.7319 | NS | BH_NS |
| TrendQuality | mid_vol | 10d | -0.0356 | 0.0000 | SIG | BH_SIG |
| TrendQuality | mid_vol | 20d | -0.0089 | 0.2623 | NS | BH_NS |
| TrendQuality | high_vol | 5d | 0.0558 | 0.0000 | SIG | BH_SIG |
| TrendQuality | high_vol | 10d | 0.0256 | 0.0073 | SIG | BH_SIG |
| TrendQuality | high_vol | 20d | 0.0050 | 0.5931 | NS | BH_NS |
| l_str_kdj_k | low_vol | 5d | -0.0095 | 0.1662 | NS | BH_NS |
| l_str_kdj_k | low_vol | 10d | -0.0398 | 0.0000 | SIG | BH_SIG |
| l_str_kdj_k | low_vol | 20d | -0.0526 | 0.0000 | SIG | BH_SIG |
| l_str_kdj_k | mid_vol | 5d | 0.0090 | 0.2500 | NS | BH_NS |
| l_str_kdj_k | mid_vol | 10d | -0.0232 | 0.0020 | SIG | BH_SIG |
| l_str_kdj_k | mid_vol | 20d | -0.0180 | 0.0208 | SIG | BH_SIG |
| l_str_kdj_k | high_vol | 5d | 0.0688 | 0.0000 | SIG | BH_SIG |
| l_str_kdj_k | high_vol | 10d | 0.0342 | 0.0002 | SIG | BH_SIG |
| l_str_kdj_k | high_vol | 20d | 0.0061 | 0.5040 | NS | BH_NS |
| l_vol_rsi_std | low_vol | 5d | 0.0026 | 0.7048 | NS | BH_NS |
| l_vol_rsi_std | low_vol | 10d | -0.0059 | 0.3863 | NS | BH_NS |
| l_vol_rsi_std | low_vol | 20d | 0.0085 | 0.2097 | NS | BH_NS |
| l_vol_rsi_std | mid_vol | 5d | -0.0152 | 0.0518 | NS | BH_NS |
| l_vol_rsi_std | mid_vol | 10d | -0.0219 | 0.0045 | SIG | BH_SIG |
| l_vol_rsi_std | mid_vol | 20d | -0.0042 | 0.5858 | NS | BH_NS |
| l_vol_rsi_std | high_vol | 5d | 0.0119 | 0.2020 | NS | BH_NS |
| l_vol_rsi_std | high_vol | 10d | 0.0115 | 0.2099 | NS | BH_NS |
| l_vol_rsi_std | high_vol | 20d | 0.0464 | 0.0000 | SIG | BH_SIG |

## L3 稳定性检验汇总

| 因子 | 状态 | 持有期 | 时间切片 | 滚动窗口 | 标的交叉 | OOS | L3 |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| TrendQuality | low_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | low_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | low_vol | 20d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | mid_vol | 5d | PASS | PASS | PASS | FAIL | PASS |
| TrendQuality | mid_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | mid_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| TrendQuality | high_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | high_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| TrendQuality | high_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | low_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | low_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | low_vol | 20d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | mid_vol | 5d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | mid_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | mid_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| l_str_kdj_k | high_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | high_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| l_str_kdj_k | high_vol | 20d | PASS | PASS | PASS | PASS | PASS |
| l_vol_rsi_std | low_vol | 5d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | low_vol | 10d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | low_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | mid_vol | 5d | PASS | PASS | PASS | PASS | PASS |
| l_vol_rsi_std | mid_vol | 10d | PASS | PASS | PASS | PASS | PASS |
| l_vol_rsi_std | mid_vol | 20d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | high_vol | 5d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | high_vol | 10d | PASS | PASS | PASS | FAIL | PASS |
| l_vol_rsi_std | high_vol | 20d | PASS | PASS | PASS | PASS | PASS |
