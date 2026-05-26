"""Upgrade report_builder.py — Phase 3: chapters 6-13."""
import re

path = r'C:\Users\17699\mozhi_platform\src\backtest\pipeline\report_builder.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# ─── Chapter 6: Trade Behavior Analysis ───
ch6_body = '''    def _chapter_6_trade_behavior(self) -> str:
        """生成交易行为分析章（含持仓时间分布、连盈连亏、月度统计）。"""
        lines = ['<div class="page-break">', "<h2>六、交易行为分析</h2>"]

        for bundle in self.bundles:
            trades = bundle.trades
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            if not trades:
                lines.append("<p>无成交记录。</p>")
                continue

            n = len(trades)
            pnls = [t.pnl for t in trades if hasattr(t, "pnl") and t.pnl is not None]
            win_trades = sum(1 for p in pnls if p > 0)
            loss_trades = sum(1 for p in pnls if p < 0)
            win_rate = win_trades / len(pnls) if pnls else 0

            # 6.2 盈亏分布统计
            lines.append("<h4>6.2 盈亏分布统计</h4>")
            if pnls:
                lines.append(_svg_bar_chart(
                    labels=[f"#{i+1}" for i in range(min(len(pnls), 40))],
                    values=pnls[:40],
                    title=f"{bundle.method_name} - 各笔盈亏分布",
                    bar_color="#2ecc71",
                ))

            # 6.3 持仓时间分布
            lines.append("<h4>6.3 持仓时间分布</h4>")
            hold_days = []
            for t in trades:
                entry = getattr(t, 'entry_time', None)
                exit_ = getattr(t, 'exit_time', None)
                if entry and exit_:
                    try:
                        diff = (pd.Timestamp(exit_) - pd.Timestamp(entry)).days
                        hold_days.append(diff)
                    except Exception:
                        pass

            if hold_days:
                avg_hold = sum(hold_days) / len(hold_days)
                min_hold = min(hold_days)
                max_hold = max(hold_days)
                lines.append(
                    '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f"<div><strong>平均持仓:</strong> {avg_hold:.1f}天</div>"
                    f"<div><strong>最短:</strong> {min_hold}天</div>"
                    f"<div><strong>最长:</strong> {max_hold}天</div>"
                    "</div>"
                )
                # 持仓分布柱状图
                if len(hold_days) > 5:
                    bins = [0, 1, 3, 5, 10, 20, 50, 100, 999]
                    labels_bin = ["0-1", "1-3", "3-5", "5-10", "10-20", "20-50", "50-100", "100+"]
                    hist = []
                    for b in range(len(bins)-1):
                        count = sum(1 for h in hold_days if bins[b] < h <= bins[b+1])
                        hist.append(count)
                    lines.append(_svg_bar_chart(
                        labels=labels_bin,
                        values=hist,
                        title=f"{bundle.method_name} - 持仓天数分布",
                        bar_color="#9b59b6",
                    ))

            # 6.5 连盈连亏序列
            lines.append("<h4>6.5 连盈连亏序列分析</h4>")
            if pnls:
                max_win_streak = max_loss_streak = 0
                cur_win = cur_loss = 0
                for p in pnls:
                    if p > 0:
                        cur_win += 1
                        cur_loss = 0
                        max_win_streak = max(max_win_streak, cur_win)
                    elif p < 0:
                        cur_loss += 1
                        cur_win = 0
                        max_loss_streak = max(max_loss_streak, cur_loss)

                profit_factor = sum(p for p in pnls if p > 0) / abs(sum(p for p in pnls if p < 0)) if any(p < 0 for p in pnls) else float('inf')
                avg_win = sum(p for p in pnls if p > 0) / win_trades if win_trades > 0 else 0
                avg_loss = sum(p for p in pnls if p < 0) / loss_trades if loss_trades > 0 else 0
                win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

                lines.append(
                    '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f"<div><strong>最大连盈:</strong> {max_win_streak}笔</div>"
                    f"<div><strong>最大连亏:</strong> {max_loss_streak}笔</div>"
                    f"<div><strong>盈亏比(ProfitFactor):</strong> {profit_factor:.2f}</div>"
                    f"<div><strong>平均盈利/亏损比:</strong> {win_loss_ratio:.2f}</div>"
                    f"<div><strong>平均盈利:</strong> {avg_win:+.4f}</div>"
                    f"<div><strong>平均亏损:</strong> {avg_loss:.4f}</div>"
                    "</div>"
                )

            lines.append(f"<p>共 {n} 笔交易，胜率 {win_rate*100:.1f}% ({win_trades}/{len(pnls)})。</p>")

        lines.append("</div>")
        return "\\n".join(lines)'''


# ─── Chapter 12: Recovery Analysis ───
ch12_body = '''    def _chapter_12_recovery_analysis(self) -> str:
        """生成连续亏损与回撤恢复章（从equity_curve和summary_metrics计算）。"""
        lines = ['<div class="page-break">', "<h2>十二、连续亏损与回撤恢复</h2>"]

        for bundle in self.bundles:
            ec = bundle.equity_curve
            trades = bundle.trades
            sm = bundle.summary_metrics
            lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")

            # 从 summary_metrics 读取
            max_dd = sm.get("max_drawdown", 0)
            pain_index = sm.get("pain_index", None)
            underwater_ratio = sm.get("underwater_ratio", None)

            lines.append("<h4>12.1 最大回撤分析</h4>")
            lines.append(
                '<div class="metric-box">'
                f"<strong>最大回撤:</strong> {max_dd*100 if isinstance(max_dd, float) else max_dd}%<br/>"
                f"<strong>Pain Index:</strong> {pain_index if pain_index is not None else '(Phase 3计算)'}<br/>"
                f"<strong>水下比例:</strong> {underwater_ratio*100 if isinstance(underwater_ratio, float) else '(Phase 3计算)'}%<br/>"
                "</div>"
            )

            # 12.2 连续亏损
            lines.append("<h4>12.2 连续亏损分析</h4>")
            if trades:
                pnls = [t.pnl for t in trades if hasattr(t, "pnl") and t.pnl is not None]
                if pnls:
                    max_consecutive_loss = 0
                    current_loss_streak = 0
                    total_loss_streak_days = 0
                    n_loss_streaks = 0
                    for p in pnls:
                        if p < 0:
                            current_loss_streak += 1
                            total_loss_streak_days += 1
                            max_consecutive_loss = max(max_consecutive_loss, current_loss_streak)
                        else:
                            if current_loss_streak > 0:
                                n_loss_streaks += 1
                            current_loss_streak = 0
                    avg_loss_streak = total_loss_streak_days / n_loss_streaks if n_loss_streaks > 0 else 0

                    lines.append(
                        '<div class="metric-box">'
                        f"<strong>最大连续亏损笔数:</strong> {max_consecutive_loss}<br/>"
                        f"<strong>平均连续亏损笔数:</strong> {avg_loss_streak:.1f}<br/>"
                        f"<strong>亏损段数:</strong> {n_loss_streaks}<br/>"
                        "</div>"
                    )

            # 12.3 水下时间
            lines.append("<h4>12.3 水下时间分析</h4>")
            if not ec.empty and "equity" in ec.columns:
                equity = ec["equity"].values
                peak = np.maximum.accumulate(equity)
                drawdown = (equity - peak) / peak
                underwater_days = int((drawdown < -0.01).sum())
                total_days = len(drawdown)
                underwater_pct = underwater_days / total_days * 100 if total_days > 0 else 0

                # 每个水下期的长度
                underwater_periods = []
                current_period = 0
                for d in drawdown:
                    if d < -0.01:
                        current_period += 1
                    else:
                        if current_period > 0:
                            underwater_periods.append(current_period)
                            current_period = 0
                if current_period > 0:
                    underwater_periods.append(current_period)

                max_underwater_period = max(underwater_periods) if underwater_periods else 0
                avg_underwater_period = sum(underwater_periods) / len(underwater_periods) if underwater_periods else 0

                lines.append(
                    '<div class="metric-box" style="display:flex;gap:16px;flex-wrap:wrap;">'
                    f"<div><strong>水下天数:</strong> {underwater_days} 天</div>"
                    f"<div><strong>水下占比:</strong> {underwater_pct:.1f}%</div>"
                    f"<div><strong>最长单次水下:</strong> {max_underwater_period} 天</div>"
                    f"<div><strong>平均每次水下:</strong> {avg_underwater_period:.1f} 天</div>"
                    f"<div><strong>水下段数:</strong> {len(underwater_periods)} 次</div>"
                    "</div>"
                )

            # 12.4 Recovery Factor
            lines.append("<h4>12.4 Recovery Factor</h4>")
            total_return = sm.get("total_return", 0)
            if isinstance(total_return, float) and isinstance(max_dd, float) and max_dd != 0:
                recovery_factor = total_return / abs(max_dd)
                lines.append(
                    '<div class="metric-box">'
                    f"<strong>Recovery Factor(总收益/最大回撤):</strong> {recovery_factor:.2f}<br/>"
                    f"<small>衡量策略的收益风险效率，越高越好。</small>"
                    "</div>"
                )

        lines.append(
            '<p class="placeholder">回撤恢复深度分析（Calmar/回撤恢复特征）：'
            "此部分在 Phase 3 实现附加指标计算。</p>"
        )
        lines.append("</div>")
        return "\\n".join(lines)'''


# ─── Chapter 11: Correlation Matrix ───
ch11_body = '''    def _chapter_11_correlation_matrix(self) -> str:
        """生成策略相关性矩阵（多策略时计算收益相关性）。"""
        lines = ['<div class="page-break">', "<h2>十一、策略相关性矩阵</h2>"]

        if len(self.bundles) < 2:
            lines.append("<p>单策略模式，无法计算相关性矩阵。需要 2 个及以上策略。</p>")
            lines.append(
                '<p class="placeholder">组合资金融合模拟：此章节在 Phase 3 实现 PortfolioManager 集成。</p>'
            )
            lines.append("</div>")
            return "\\n".join(lines)

        # 从各 bundle 的 equity_curve 计算相关性
        returns = {}
        for b in self.bundles:
            ec = b.equity_curve
            if not ec.empty and "return" in ec.columns:
                returns[b.method_name] = ec["return"]

        if len(returns) >= 2:
            # 对齐索引
            df = pd.DataFrame(returns)
            df = df.dropna()

            if len(df) > 20:
                corr = df.corr()
                lines.append("<h4>11.1 日收益率相关性矩阵</h4>")
                lines.append("<table>")
                th = "<tr><th></th>" + "".join(f"<th>{html_mod.escape(c)}</th>" for c in corr.columns) + "</tr>"
                lines.append(th)
                for rname, row in corr.iterrows():
                    td = "".join(
                        f'<td style="color:{"#e74c3c" if v > 0 else "#2ecc71" if v < 0 else "#888"}">{v:.3f}</td>'
                        for _, v in row.items()
                    )
                    lines.append(f"<tr><td><strong>{html_mod.escape(rname)}</strong></td>{td}</tr>")
                lines.append("</table>")

                # 最大正相关/负相关
                pairs = []
                for i in range(len(corr.columns)):
                    for j in range(i+1, len(corr.columns)):
                        pairs.append((corr.iloc[i, j], corr.columns[i], corr.columns[j]))
                pairs.sort(key=lambda x: abs(x[0]), reverse=True)

                if pairs:
                    lines.append("<h4>相关性排序</h4>")
                    lines.append("<table><tr><th>策略A</th><th>策略B</th><th>相关性</th></tr>")
                    for r_val, a, b in pairs[:6]:
                        color = "#e74c3c" if r_val > 0 else "#2ecc71"
                        lines.append(
                            f"<tr><td>{html_mod.escape(a)}</td><td>{html_mod.escape(b)}</td>"
                            f'<td style="color:{color}">{r_val:.3f}</td></tr>'
                        )
                    lines.append("</table>")

            else:
                lines.append("<p>数据点不足（<20个交易日），无法计算有意义的相关系数。</p>")
        else:
            lines.append("<p>无收益率数据可用于相关性计算。</p>")

        lines.append(
            '<p class="placeholder">组合资金融合模拟：此章节在 Phase 3 实现 PortfolioManager 集成 '
            '和等权/最小方差/风险平价配权重计算。</p>'
        )
        lines.append("</div>")
        return "\\n".join(lines)'''


# ─── Chapter 13: T1 Rating ───
ch13_body = '''    def _chapter_13_t1_rating(self) -> str:
        """生成T1多维评分矩阵（从summary_metrics计算各维度评分）。"""
        lines = ['<div class="page-break">', "<h2>十三、T1评级结论</h2>",
                 "<p>多方法/策略的多维评分矩阵：每个维度满分10分。</p>"]

        if not self.bundles:
            lines.append("<p>无策略数据。</p>")
            lines.append("</div>")
            return "\\n".join(lines)

        # 定义评分维度及对应的summary_metrics key、权重、方向
        dimensions = [
            ("总收益", ["total_return"], 1.0, True),
            ("年化收益", ["annual_return"], 1.0, True),
            ("夏普比率", ["sharpe"], 1.0, True),
            ("风险控制", ["max_drawdown"], 0.5, False),
            ("交易质量", ["win_rate", "profit_factor"], 1.0, True),
            ("恢复能力", ["recovery_factor"], 1.0, True),
        ]

        # 计算每个策略在每个维度的原始值
        method_scores: Dict[str, Dict[str, float]] = {}
        for b in self.bundles:
            sm = b.summary_metrics
            method_scores[b.method_name] = {}
            for dim_name, keys, _, _ in dimensions:
                vals = [sm.get(k, 0) for k in keys]
                # 对多个key取平均
                non_none = [v for v in vals if v is not None and isinstance(v, (int, float))]
                method_scores[b.method_name][dim_name] = sum(non_none) / len(non_none) if non_none else 0

        # 每个维度归一化到0-10
        dim_max: Dict[str, float] = {}
        dim_min: Dict[str, float] = {}
        for dim_name, _, _, higher_ok in dimensions:
            vals = [method_scores[m][dim_name] for m in method_scores]
            if higher_ok:
                dim_max[dim_name] = max(vals) if vals else 1
                dim_min[dim_name] = min(vals) if vals else 0
            else:
                # 对于lower_is_better（最大回撤），取绝对值
                abs_vals = [abs(v) for v in vals]
                dim_max[dim_name] = max(abs_vals) if abs_vals else 1
                dim_min[dim_name] = min(abs_vals) if abs_vals else 0

        # 归一化到0-10
        def _normalize(val: float, dim: str, higher_ok: bool) -> float:
            dmax = dim_max.get(dim, 1)
            dmin = dim_min.get(dim, 0)
            drange = dmax - dmin if dmax != dmin else 1
            if higher_ok:
                # 越高越好: v -> dmin->0, dmax->10
                return min(max((val - dmin) / drange * 10, 0), 10)
            else:
                # 越低越好: v -> dmin->10, dmax->0
                return min(max((dmax - abs(val)) / drange * 10, 0), 10)

        # 构建评分表格
        lines.append("<table>")
        th = "<tr><th>策略/方法</th>"
        for dim_name, _, _, _ in dimensions:
            th += f"<th>{html_mod.escape(dim_name)}</th>"
        th += "<th>综合评分</th></tr>"
        lines.append(th)

        for b in self.bundles:
            row = f"<tr><td><strong>{html_mod.escape(b.method_name)}</strong></td>"
            scores = []
            for dim_name, _, _, higher_ok in dimensions:
                raw = method_scores[b.method_name][dim_name]
                normalized = _normalize(raw, dim_name, higher_ok)
                scores.append(normalized)
                color = "#2ecc71" if normalized >= 7 else ("#f39c12" if normalized >= 4 else "#e74c3c")
                row += f'<td style="color:{color}">{normalized:.1f}</td>'
            # 综合评分（各维度等权平均）
            avg_score = sum(scores) / len(scores)
            avg_color = "#2ecc71" if avg_score >= 7 else ("#f39c12" if avg_score >= 4 else "#e74c3c")
            row += f'<td style="color:{avg_color};font-weight:bold;">{avg_score:.1f}</td></tr>'
            lines.append(row)

        lines.append("</table>")

        lines.append(
            '<div class="metric-box">'
            "<strong>评分说明：</strong><br/>"
            "各维度基于实际指标值在策略间的相对排名归一化到0-10分。<br/>"
            "<span style='color:#2ecc71'>高分(≥7)</span> = 优秀 | "
            "<span style='color:#f39c12'>中分(4-7)</span> = 一般 | "
            "<span style='color:#e74c3c'>低分(&lt;4)</span> = 需改进<br/>"
            "<small>注意：评分在单策略模式下无法做相对比较，各项均为10分。</small>"
            "</div>"
        )

        lines.append("</div>")
        return "\\n".join(lines)'''


# ─── Chapter 7: Regime (semi-structured, partial data) ───
ch7_body = '''    def _chapter_7_regime_adaptation(self) -> str:
        """生成市场状态适应性章（尝试读取regime_labels，否则占位）。"""
        lines = ['<div class="page-break">', "<h2>七、市场状态适应性</h2>"]

        has_regime_data = any(
            not b.regime_labels.empty for b in self.bundles
        )

        if has_regime_data:
            for bundle in self.bundles:
                rl = bundle.regime_labels
                lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")
                if not rl.empty:
                    lines.append("<p>市场状态标签可用，展示各状态下的表现。</p>")
                    if "regime" in rl.columns:
                        lines.append("<table><tr><th>日期</th><th>市场状态</th></tr>")
                        for idx, row in rl.iterrows():
                            dt = str(idx.date()) if hasattr(idx, 'date') else str(idx)
                            lines.append(f"<tr><td>{dt}</td><td>{html_mod.escape(str(row.get('regime', '')))}</td></tr>")
                        lines.append("</table>")
                else:
                    lines.append("<p>无市场状态数据。</p>")
        else:
            lines.append("<p>无市场状态标签数据。Phase 3 实现 Regime 分类算法后可用。</p>")

        lines.append(
            '<div class="placeholder">'
            "<p><strong>此章节在 Phase 3 实现完整分析：</strong></p>"
            "<pre>"
            "7.1 By Regime（牛市/震荡/熊市）\n"
            "7.2 高波动 vs 低波动期\n"
            "7.3 成交量放大期\n"
            "7.4 板块轮动期（预留）\n\n"
            "需要 Regime 分类算法（从 df_ohlcv 计算趋势强度/波动率/成交量特征）"
            "</pre>"
            "</div>"
        )
        lines.append("</div>")
        return "\\n".join(lines)'''


# ─── Chapter 9: Param Sensitivity ───
ch9_body = '''    def _chapter_9_param_sensitivity(self) -> str:
        """生成参数敏感性分析章（读取parameter_scan，否则占位）。"""
        lines = ['<div class="page-break">', "<h2>九、参数敏感性分析</h2>"]

        has_scan_data = any(
            not b.parameter_scan.empty for b in self.bundles
        )

        if has_scan_data:
            for bundle in self.bundles:
                ps = bundle.parameter_scan
                lines.append(f"<h3>{html_mod.escape(bundle.method_name)}</h3>")
                if not ps.empty:
                    lines.append("<p>参数扫描结果：</p>")
                    lines.append(self._table_from_series(
                        headers=list(ps.columns),
                        rows=[[str(v) for v in row] for _, row in ps.iterrows()],
                        caption="参数扫描结果",
                    ))
                else:
                    lines.append("<p>无参数扫描数据。</p>")
        else:
            lines.append("<p>无参数扫描数据。Phase 3 实现参数扫描引擎后可用。</p>")

        lines.append(
            '<div class="placeholder">'
            "<p><strong>此章节在 Phase 3 实现：</strong></p>"
            "<pre>"
            "9.1 关键参数扫描（遍历参数空间）\n"
            "9.2 参数稳定性评分（RobustScore）\n\n"
            "基础算法: 对每个参数在其取值范围内扫描,\n"
            "计算 Sharpe/Return/DD 的变异系数,\n"
            "变异系数越低 = 参数越鲁棒"
            "</pre>"
            "</div>"
        )
        lines.append("</div>")
        return "\\n".join(lines)'''


# Map method name -> new body
replacements = {
    '    def _chapter_6_trade_behavior(self) -> str:': ch6_body,
    '    def _chapter_7_regime_adaptation(self) -> str:': ch7_body,
    '    def _chapter_9_param_sensitivity(self) -> str:': ch9_body,
    '    def _chapter_11_correlation_matrix(self) -> str:': ch11_body,
    '    def _chapter_12_recovery_analysis(self) -> str:': ch12_body,
    '    def _chapter_13_t1_rating(self) -> str:': ch13_body,
}

for sig, new_body in replacements.items():
    idx = content.find(sig)
    if idx < 0:
        print(f"ERROR: cannot find {sig}")
        continue

    # Find the method body: from this line to next def or end
    method_start = content.rfind('\n', 0, idx) + 1

    # Find the end: next top-level def or end of file
    next_def = content.find('\n    def ', idx + 1)
    if next_def < 0:
        next_def = len(content)

    old = content[method_start:next_def]
    content = content[:method_start] + new_body + content[next_def:]
    print(f"Replaced {sig.strip()}")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done")
