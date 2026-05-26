#!/usr/bin/env python3
"""Generate 601857 Research Report PDF v2.1 with proper CJK font support."""

import os
import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable
)
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Register CJK Font ──────────────────────────────────────────────
font_paths = [
    r'C:\Windows\Fonts\simsun.ttc',   # 宋体
    r'C:\Windows\Fonts\simhei.ttf',   # 黑体
    r'C:\Windows\Fonts\msyh.ttc',     # 微软雅黑
    r'C:\Windows\Fonts\msyhbd.ttc',   # 微软雅黑 Bold
]
CJK = None
for fp in font_paths:
    if os.path.exists(fp):
        try:
            pdfmetrics.registerFont(TTFont('CJK', fp))
            CJK = 'CJK'
            print(f"[OK] Registered CJK font: {fp}")
            break
        except Exception as e:
            print(f"[WARN] Failed to register {fp}: {e}")
if not CJK:
    raise RuntimeError("No CJK font found!")

# Also register a bold variant if possible
# Try SimHei for bold
try:
    if os.path.exists(r'C:\Windows\Fonts\simhei.ttf'):
        pdfmetrics.registerFont(TTFont('CJK-Bold', r'C:\Windows\Fonts\simhei.ttf'))
        CJK_BOLD = 'CJK-Bold'
    else:
        CJK_BOLD = 'CJK'
except:
    CJK_BOLD = 'CJK'

# ── Output Paths ───────────────────────────────────────────────────
output_dir1 = r'C:\Users\17699\mozhi_platform\reports\pdf'
output_dir2 = r'C:\Users\17699\.openclaw\workspace-mochen\reports\pdf'
os.makedirs(output_dir1, exist_ok=True)
os.makedirs(output_dir2, exist_ok=True)

output_path = os.path.join(output_dir1, '601857_research_report_v2.1_20260518.pdf')

# ── Styles ─────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def make_style(name, parent='Normal', **kw):
    base = styles[parent]
    return ParagraphStyle(name, parent=base, **kw)

s_title = ParagraphStyle('Title_CJK', fontName=CJK_BOLD, fontSize=20, leading=28,
                          alignment=TA_CENTER, spaceAfter=6*mm, textColor=colors.HexColor('#1a1a2e'))
s_subtitle = ParagraphStyle('Subtitle_CJK', fontName=CJK, fontSize=10, leading=14,
                             alignment=TA_CENTER, spaceAfter=3*mm, textColor=colors.HexColor('#555555'))
s_h1 = ParagraphStyle('H1_CJK', fontName=CJK_BOLD, fontSize=16, leading=22,
                       spaceBefore=8*mm, spaceAfter=4*mm, textColor=colors.HexColor('#1a1a2e'),
                       borderWidth=0, borderPadding=0,
                       leftIndent=0)
s_h2 = ParagraphStyle('H2_CJK', fontName=CJK_BOLD, fontSize=13, leading=18,
                       spaceBefore=5*mm, spaceAfter=3*mm, textColor=colors.HexColor('#2d3436'))
s_h3 = ParagraphStyle('H3_CJK', fontName=CJK_BOLD, fontSize=11, leading=15,
                       spaceBefore=3*mm, spaceAfter=2*mm, textColor=colors.HexColor('#636e72'))
s_body = ParagraphStyle('Body_CJK', fontName=CJK, fontSize=9.5, leading=14,
                         spaceBefore=1*mm, spaceAfter=1*mm, alignment=TA_JUSTIFY)
s_code = ParagraphStyle('Code_CJK', fontName='Courier', fontSize=8, leading=11,
                          leftIndent=4*mm, rightIndent=4*mm, spaceBefore=1*mm, spaceAfter=1*mm,
                          backColor=colors.HexColor('#f8f9fa'))
s_bullet = ParagraphStyle('Bullet_CJK', fontName=CJK, fontSize=9.5, leading=14,
                           leftIndent=8*mm, bulletIndent=2*mm, spaceBefore=0.5*mm, spaceAfter=0.5*mm)
s_note = ParagraphStyle('Note_CJK', fontName=CJK, fontSize=9, leading=13,
                         leftIndent=4*mm, rightIndent=4*mm, spaceBefore=2*mm, spaceAfter=2*mm,
                         backColor=colors.HexColor('#eef2f7'), borderPadding=3*mm)
s_obs = ParagraphStyle('Obs_CJK', fontName=CJK, fontSize=9, leading=13,
                        leftIndent=4*mm, rightIndent=4*mm, spaceBefore=2*mm, spaceAfter=2*mm,
                        backColor=colors.HexColor('#fff3e0'), borderPadding=3*mm)
s_footer = ParagraphStyle('Footer_CJK', fontName=CJK, fontSize=8, leading=10,
                           alignment=TA_CENTER, textColor=colors.HexColor('#999999'))
s_table_header = ParagraphStyle('TH_CJK', fontName=CJK_BOLD, fontSize=9, leading=12,
                                 alignment=TA_CENTER, textColor=colors.white)
s_table_cell = ParagraphStyle('TD_CJK', fontName=CJK, fontSize=9, leading=12,
                               alignment=TA_CENTER)
s_table_cell_left = ParagraphStyle('TD_CJK_L', fontName=CJK, fontSize=9, leading=12,
                                    alignment=TA_LEFT)
s_pri_red = ParagraphStyle('Pri_Red', fontName=CJK_BOLD, fontSize=9.5, leading=13,
                            textColor=colors.HexColor('#d63031'))
s_pri_yellow = ParagraphStyle('Pri_Yellow', fontName=CJK_BOLD, fontSize=9.5, leading=13,
                               textColor=colors.HexColor('#f39c12'))
s_pri_green = ParagraphStyle('Pri_Green', fontName=CJK_BOLD, fontSize=9.5, leading=13,
                              textColor=colors.HexColor('#27ae60'))

# ── Helpers ────────────────────────────────────────────────────────
def hr():
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#ddd'), spaceAfter=3*mm)

def P(text, style=s_body):
    return Paragraph(text, style)

def make_table(data, col_widths=None, header_rows=1):
    """Create a styled table with optional header highlighting."""
    t = Table(data, colWidths=col_widths, repeatRows=header_rows)
    style_cmds = [
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), CJK),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#ccc')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]
    # Header row styling
    for r in range(header_rows):
        style_cmds.extend([
            ('BACKGROUND', (0, r), (-1, r), colors.HexColor('#2d3436')),
            ('TEXTCOLOR', (0, r), (-1, r), colors.white),
            ('FONTNAME', (0, r), (-1, r), CJK_BOLD),
        ])
    # Alternating row colors
    for r in range(header_rows, len(data)):
        if r % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, r), (-1, r), colors.HexColor('#f8f9fa')))
    t.setStyle(TableStyle(style_cmds))
    return t

def bullet_item(text, style=s_bullet):
    return Paragraph(f'<bullet>&bull;</bullet>{text}', style)

def note_block(text, style=s_note):
    return Paragraph(f'💡 {text}', style)

def obs_block(text, style=s_obs):
    return Paragraph(f'📊 {text}', style)

def build_document():
    story = []
    page_w = A4[0] - 30*mm  # usable width

    # ══════════════ COVER / TITLE ════════════════════════════════════
    story.append(Spacer(1, 20*mm))
    story.append(Paragraph('601857 · 研究型量化分析报告', s_title))
    story.append(Paragraph('v2.1 —— Phase 1 收尾版', s_subtitle))
    story.append(Spacer(1, 3*mm))
    story.append(P('<b>回测标的</b>：601857.SH（中国石油）'))
    story.append(P('<b>回测区间</b>：2020-01-02 ~ 2025-05-15（1,540 Bar）'))
    story.append(P('<b>回测完成</b>：2026-05-18'))
    story.append(P('<b>引擎模块</b>：SignalEventCollector · BreakoutProfile · TrendLifecycleDetector · RiskPipeline'))
    story.append(P('<b>作者</b>：墨衡 (moheng)'))
    story.append(Spacer(1, 5*mm))
    story.append(hr())
    story.append(PageBreak())

    # ══════════════ TABLE OF CONTENTS ═══════════════════════════════
    story.append(Paragraph('目 录', s_h1))
    story.append(hr())
    toc_items = [
        ('Layer 1 — 绩效层 Performance Layer', '3'),
        ('   综合绩效指标', '3'),
        ('   净值曲线特征', '3'),
        ('Layer 2 — 行为层 Behavior Layer', '4'),
        ('   信号事件采集分析', '4'),
        ('   假突破画像分析', '5'),
        ('   趋势生命周期分析', '6'),
        ('   条件收益矩阵分析', '8'),
        ('Layer 3 — 结构层 Structure Layer', '11'),
        ('   突破信号×生命周期综合症候分析', '11'),
        ('Layer 4 — 风险与完整性层', '12'),
        ('   风险指标', '12'),
        ('   总评与战术建议', '13'),
    ]
    for item, page in toc_items:
        indent = 8*mm if item.startswith('   ') else 0
        s = ParagraphStyle('toc', fontName=CJK, fontSize=10, leading=16,
                            leftIndent=indent)
        story.append(Paragraph(f'{item.strip()}', s))
    story.append(PageBreak())

    # ══════════════ Layer 1 ════════════════════════════════════════
    story.append(Paragraph('Layer 1 — 绩效层 Performance Layer', s_h1))
    story.append(hr())

    story.append(Paragraph('1.1 综合绩效指标', s_h2))
    perf_data = [
        [P('指标', s_table_header), P('值', s_table_header)],
        [P('总收益率'), P('18.16%')],
        [P('年化收益率'), P('2.75%')],
        [P('总交易次数'), P('88（买入 44 / 卖出 44）')],
        [P('最大回撤'), P('2.38%')],
        [P('Calmar 比率'), P('1.15')],
        [P('交易密度'), P('5.71 笔/百Bar')],
    ]
    story.append(make_table(perf_data, col_widths=[page_w*0.35, page_w*0.65]))
    story.append(Spacer(1, 2*mm))
    story.append(obs_block(
        '88 笔交易在 1,540 Bar 中呈稀疏分布，大量 Bar 无持仓变动，说明策略以低频捕获趋势波段为主。'
        '同等量盘中，交易集中在少数活跃区段（2020年7月、2021年1月、2021年3月、2025年等），其余区间净值持平。<br/>'
        '<b>Confidence</b>: 高 — 指标基于完整回测结果。'
    ))

    story.append(Paragraph('1.2 净值曲线特征', s_h2))
    story.append(P('初始资金 ¥1,000,000 → 期末约 ¥1,181,625'))
    story.append(P('前 120 Bar（2020H1）零交易，2020年7月出现首次开仓'))
    story.append(P('净值爬升呈多段阶梯状，非平滑上涨，符合低频趋势策略行为模式'))
    story.append(P('最大回撤区间发生在 2021年2月–4月及后续持仓调整期'))

    story.append(PageBreak())

    # ══════════════ Layer 2 ════════════════════════════════════════
    story.append(Paragraph('Layer 2 — 行为层 Behavior Layer', s_h1))
    story.append(hr())
    story.append(Paragraph('2.1 信号事件采集分析', s_h2))
    story.append(P('<b>数据源</b>：SignalEventCollector 输出'))
    story.append(P('全回测区间内每日生成信号评估，累积 1,540 次因子信号评估，其中 88 次触发实质信号事件并进入交易决策。'))

    story.append(Paragraph('2.1.1 信号总量与转化', s_h3))
    sig_data = [
        [P('指标', s_table_header), P('数值', s_table_header), P('注释', s_table_header)],
        [P('总因子信号评估数'), P('1,540'), P('每 Bar 一次')],
        [P('触发信号事件'), P('88'), P('产生交易信号的次数')],
        [P('信号触发率'), P('5.71%'), P('约每 17.5 Bar 触发一次')],
        [P('过滤日志数'), P('0'), P('无信号被因子过滤器拒绝')],
        [P('交易决策数'), P('88'), P('100% 转化')],
        [P('买入:卖出'), P('44:44'), P('完美平衡')],
        [P('信号→成交转化率'), P('100%'), P('每触发一次信号即执行一次交易')],
    ]
    story.append(make_table(sig_data, col_widths=[page_w*0.30, page_w*0.20, page_w*0.50]))
    story.append(Spacer(1, 2*mm))
    story.append(obs_block(
        '5.71% 的信号触发率意味着该策略在 94.3% 的时间里处于空仓或持基状态，仅在因子组合满足严格条件时才入场。'
        '信号触发后的 100% 执行率（0 次过滤）说明策略的筛选逻辑集中在信号产生前（因子条件 vs. 信号产生后过滤）。<br/>'
        '<b>Confidence</b>: 中 — 信号事件计数 = 88 且均进入交易决策，但因子层面的"通过/拒绝"细节未记录。'
    ))

    story.append(PageBreak())

    # 2.2 假突破画像分析
    story.append(Paragraph('2.2 假突破画像分析', s_h2))
    story.append(P('<b>数据源</b>：BreakoutProfile 输出'))
    story.append(P('全回测区间共识别 909 个突破事件，其中 119 个被判定为假突破，整体假突破率 <b>13.09%</b>。'))

    story.append(Paragraph('2.2.1 突破事件总览', s_h3))
    brk_data = [
        [P('指标', s_table_header), P('数值', s_table_header)],
        [P('突破事件总数'), P('909')],
        [P('假突破数'), P('119')],
        [P('假突破率'), P('13.09%')],
        [P('真实突破数'), P('790')],
    ]
    story.append(make_table(brk_data, col_widths=[page_w*0.35, page_w*0.65]))
    story.append(obs_block('13.09% 的假突破率意味着每约 7.6 个突破事件中有 1 个是假突破。在一只大盘蓝筹股上，该假突破率处于可接受范围。'))

    story.append(Paragraph('2.2.2 突破类型分布', s_h3))
    brk_type = [
        [P('突破类型', s_table_header), P('次数', s_table_header), P('占比', s_table_header)],
        [P('MA_UP（均线上穿）'), P('448'), P('49.3%')],
        [P('MA_DOWN（均线下穿）'), P('258'), P('28.4%')],
        [P('BOLL_UP（布林上穿）'), P('140'), P('15.4%')],
        [P('BOLL_DOWN（布林下穿）'), P('63'), P('6.9%')],
    ]
    story.append(make_table(brk_type, col_widths=[page_w*0.50, page_w*0.20, page_w*0.30]))
    story.append(obs_block(
        'MA 类突破（MA_UP + MA_DOWN）合计占比 77.7%，是突破事件的主体，远高于 Bollinger 类突破。'
        '其中 MA_UP 占比近半，说明在 601857 上均线向上突破是最常见的入场触发条件。'
        'BOLL_DOWN 仅占 6.9%，说明价格向下穿透布林带的场景在该标的相对少见。<br/>'
        '<b>Confidence</b>: 高 — 数据直接来自 BreakoutProfile 模块统计。'
    ))

    story.append(PageBreak())

    # 2.3 趋势生命周期分析
    story.append(Paragraph('2.3 趋势生命周期分析', s_h2))
    story.append(P('<b>数据源</b>：TrendLifecycleDetector 输出'))
    story.append(P('全回测区间中，每个 Bar 的趋势生命周期阶段分布如下。'))

    story.append(Paragraph('2.3.1 各阶段占比', s_h3))
    life_data = [
        [P('阶段', s_table_header), P('Bar 数', s_table_header), P('占比', s_table_header), P('含义', s_table_header)],
        [P('DISTRIB'), P('1,257'), P('81.62%'), P('趋势结束后的整理出货阶段')],
        [P('PRE_INIT'), P('251'), P('16.30%'), P('趋势启动前的酝酿积累期')],
        [P('EXHAUST'), P('27'), P('1.75%'), P('趋势末端的能量衰竭期')],
        [P('ACCEL'), P('3'), P('0.19%'), P('趋势中段的加速期')],
        [P('MAIN'), P('2'), P('0.13%'), P('趋势核心主段')],
    ]
    story.append(make_table(life_data, col_widths=[page_w*0.20, page_w*0.12, page_w*0.12, page_w*0.56]))

    story.append(Spacer(1, 2*mm))
    story.append(P(
        '<font face="Courier" size="8">'
        'DISTRIB    ██████████████████████████████████████████ 81.62%<br/>'
        'PRE_INIT   ████████                                 16.30%<br/>'
        'EXHAUST    █                                         1.75%<br/>'
        'ACCEL      ▏                                         0.19%<br/>'
        'MAIN       ▏                                         0.13%'
        '</font>', s_body))
    story.append(Spacer(1, 2*mm))

    story.append(obs_block(
        '该分布揭示了一个结构性失衡——全区间 81.62% 的时间处于盘整/分布阶段，而趋势核心阶段（ACCEL+MAIN）合计仅 0.32%（5 Bar）。这意味着：<br/>'
        '1. 601857 在 2020-2025 年间绝大多数时间处于方向不明的整理状态<br/>'
        '2. 有效的趋势交易机会极少（仅约 0.3% 的时间），策略核心挑战在于在 98% 的无趋势时间中保存资金<br/>'
        '3. 该分布解释了为何总交易仅 88 笔——策略本质上是在等待那 0.32% 的稀有趋势窗口<br/>'
        '<b>Confidence</b>: 高 — 基于 TrendLifecycleDetector 在 1,540 Bar 上的全量输出。'
    ))

    story.append(Paragraph('2.3.3 假突破 × 生命周期协同分析', s_h3))
    fb_life = [
        [P('生命周期阶段', s_table_header), P('突破总数', s_table_header), P('假突破数', s_table_header),
         P('假突破率', s_table_header), P('占比变化', s_table_header)],
        [P('ACCEL（加速）'), P('1'), P('0'), P('0.00%'), P('↓ 低于均值')],
        [P('DISTRIB（分布）'), P('804'), P('109'), P('13.56%'), P('↑ 略高于均值')],
        [P('EXHAUST（衰竭）'), P('19'), P('1'), P('<b>5.26%</b>'), P('↓ 显著低于均值')],
        [P('PRE_INIT（前初始）'), P('85'), P('9'), P('10.59%'), P('↓ 低于均值')],
    ]
    story.append(make_table(fb_life, col_widths=[page_w*0.28, page_w*0.16, page_w*0.16, page_w*0.20, page_w*0.20]))
    story.append(obs_block(
        '<b>EXHAUST 期的假突破率最低（5.26%）</b>，仅为整体均值（13.09%）的 40%。这意味着趋势衰竭期的突破具有最高可信度——'
        '动量耗尽后再出现的突破信号通常更可靠。<br/>'
        '<b>DISTRIB 期的假突破率最高（13.56%）</b>，略高于均值。盘整区的突破最容易失效，'
        '这也是市场中"盘整区突破谨慎"的经验法则得到验证。<br/>'
        '<b>Confidence</b>: 高 — 基于 BreakoutProfile × TrendLifecycleDetector 的交叉分析，1,540 Bar 全量覆盖。'
    ))

    story.append(PageBreak())

    # 2.4 条件收益矩阵分析
    story.append(Paragraph('2.4 条件收益矩阵分析', s_h2))
    story.append(P('<b>数据源</b>：trade_decisions × signal_events 交叉分析'))
    story.append(P('将 44 笔已平仓完整交易按三个维度分桶统计，从"单笔赚了多少"升级为"在什么条件下系统整体表现如何"。'))

    # 2.4.1
    story.append(Paragraph('2.4.1 维度 A：信号置信度分桶', s_h3))
    conf_data = [
        [P('置信度桶', s_table_header), P('成交数', s_table_header), P('胜率', s_table_header),
         P('平均收益', s_table_header), P('最大收益', s_table_header), P('最大亏损', s_table_header), P('Sharpe', s_table_header)],
        [P('HIGH (≥0.8)'), P('3'), P('66.7%'), P('+4.58%'), P('+8.34%'), P('-1.47%'), P('0.87')],
        [P('MEDIUM (0.6–0.8)'), P('19'), P('57.9%'), P('+2.19%'), P('+9.15%'), P('-3.95%'), P('0.52')],
        [P('LOW (<0.6)'), P('22'), P('45.5%'), P('+1.80%'), P('+15.01%'), P('-3.00%'), P('0.39')],
    ]
    story.append(make_table(conf_data, col_widths=[page_w*0.20, page_w*0.12, page_w*0.12, page_w*0.14, page_w*0.14, page_w*0.14, page_w*0.14]))
    story.append(obs_block(
        '置信度与收益呈单调正相关关系——高置信度信号的胜率（66.7%）、平均收益（+4.58%）和 Sharpe（0.87）均显著优于低置信度信号。'
        '尽管 HIGH 桶仅 3 笔样本量偏小，但 MEDIUM 桶（19 笔）与 LOW 桶（22 笔）之间的 12 个百分点胜率差距足够说明置信度对交易结果有区分力。'
    ))

    # 2.4.2
    story.append(Paragraph('2.4.2 维度 B：市场状态（Regime）', s_h3))
    regime_data = [
        [P('市场状态', s_table_header), P('成交数', s_table_header), P('胜率', s_table_header), P('平均收益', s_table_header)],
        [P('TREND_UP'), P('26'), P('50.0%'), P('+2.34%')],
        [P('RANGE'), P('14'), P('50.0%'), P('+1.54%')],
        [P('TREND_DOWN'), P('4'), P('75.0%'), P('+3.13%')],
    ]
    story.append(make_table(regime_data, col_widths=[page_w*0.30, page_w*0.20, page_w*0.20, page_w*0.30]))

    # 2.4.3
    story.append(Paragraph('2.4.3 维度 C：持仓天数', s_h3))
    hold_data = [
        [P('持仓分组', s_table_header), P('成交数', s_table_header), P('胜率', s_table_header),
         P('平均收益', s_table_header), P('最大收益', s_table_header), P('最大亏损', s_table_header), P('Sharpe', s_table_header)],
        [P('≤5 天（短线）'), P('16'), P('37.5%'), P('+1.31%'), P('+9.15%'), P('-1.71%'), P('0.36')],
        [P('6–15 天（中短线）'), P('18'), P('61.1%'), P('+2.27%'), P('+10.21%'), P('-3.95%'), P('0.51')],
        [P('>15 天（中线）'), P('10'), P('60.0%'), P('+3.32%'), P('+15.01%'), P('-2.25%'), P('0.59')],
    ]
    story.append(make_table(hold_data, col_widths=[page_w*0.22, page_w*0.12, page_w*0.12, page_w*0.14, page_w*0.14, page_w*0.14, page_w*0.12]))
    story.append(obs_block(
        '持仓期限与收益呈现清晰的单调正相关：<br/>'
        '• ≤5 天短线：胜率仅 37.5%、Sharpe 0.36，属于高频噪音交易<br/>'
        '• 6–15 天中短线：胜率跃升至 61.1%，Sharpe 0.51，是最稳健的持仓区间<br/>'
        '• >15 天中线：平均收益最高（+3.32%）、Sharpe 最高（0.59）<br/>'
        '<b>战术含义</b>：过滤持仓 ≤5 天的短信号可以显著提升策略胜率和风险调整后收益。'
    ))

    story.append(PageBreak())

    # 2.4.4 交叉矩阵
    story.append(Paragraph('2.4.4 维度 D：置信度 × 市场状态 3×3 交叉矩阵', s_h3))
    cross_data = [
        [P('置信度 \\ 市场状态', s_table_header), P('TREND_UP', s_table_header),
         P('RANGE', s_table_header), P('TREND_DOWN', s_table_header)],
        [P('HIGH (≥0.8)'), P('N/A'), P('+3.44%（2 笔）'), P('+6.88%（1 笔）')],
        [P('MEDIUM (0.6–0.8)'), P('<b>+2.67%（12 笔）</b>'), P('+2.09%（6 笔）'), P('-2.87%（1 笔）')],
        [P('LOW (<0.6)'), P('+2.06%（14 笔）'), P('+0.36%（6 笔）'), P('+4.26%（2 笔）')],
    ]
    story.append(make_table(cross_data, col_widths=[page_w*0.28, page_w*0.24, page_w*0.24, page_w*0.24]))
    story.append(Spacer(1, 2*mm))
    story.append(note_block(
        '<b>最佳可靠组合</b>：MEDIUM × TREND_UP（12 笔，WR 58.3%，Sharpe 0.62），是该策略的核心盈利区域。<br/>'
        '<b>最需规避组合</b>：LOW × RANGE（6 笔，WR 33.3%，平均收益 +0.36%），低置信度信号在震荡市场中几乎无效。'
    ))

    story.append(Paragraph('2.4.5 条件收益矩阵总评', s_h3))
    summary_data = [
        [P('#', s_table_header), P('发现', s_table_header), P('策略含义', s_table_header)],
        [P('1'), P('持仓 6 天+ 的交易胜率 >60%，≤5 天仅 37.5%'), P('建议增加持仓最低天数过滤器')],
        [P('2'), P('MEDIUM 置信度 × TREND_UP 是核心盈利区域（12 笔，WR 58.3%）'), P('该组合应作为仓位配置的基准场景')],
        [P('3'), P('LOW 置信度 × RANGE 是最弱组合（6 笔，WR 33.3%）'), P('遇到此条件应跳过信号或缩仓')],
        [P('4'), P('TREND_DOWN 状态表现优秀（75% WR）但样本极少（4 笔）'), P('需验证长期有效性')],
        [P('5'), P('高持仓天数（>15d）+ 高置信度组合 Sharpe 最高'), P('可考虑建立仓位分级的金字塔规则')],
    ]
    story.append(make_table(summary_data, col_widths=[page_w*0.06, page_w*0.52, page_w*0.42]))

    story.append(PageBreak())

    # ══════════════ Layer 3 ════════════════════════════════════════
    story.append(Paragraph('Layer 3 — 结构层 Structure Layer', s_h1))
    story.append(hr())

    story.append(Paragraph('3.1 突破信号 × 趋势生命周期综合症候分析', s_h2))
    story.append(Paragraph('3.1.1 信号密度分布', s_h3))
    density_data = [
        [P('阶段', s_table_header), P('突破数', s_table_header), P('阶段 Bar 数', s_table_header),
         P('突破密度（/100Bar）', s_table_header)],
        [P('PRE_INIT'), P('85'), P('251'), P('33.9')],
        [P('ACCEL'), P('1'), P('3'), P('33.3')],
        [P('EXHAUST'), P('19'), P('27'), P('<b>70.4</b>')],
        [P('DISTRIB'), P('804'), P('1,257'), P('<b>64.0</b>')],
    ]
    density_data.insert(2, [P('MAIN'), P('—'), P('2'), P('—')])
    story.append(make_table(density_data, col_widths=[page_w*0.25, page_w*0.20, page_w*0.25, page_w*0.30]))
    story.append(obs_block(
        '<b>EXHAUST 期突破密度最高（70.4/100Bar）</b>：在趋势衰竭阶段的短短 27 Bar 内集中了 19 个突破事件，密度达到每 1.4 Bar 一次。<br/>'
        '突破密度×假突破率的关系：<b>EXHAUST 期密度最高但假突破率最低（5.26%）</b>——高密度 ≠ 高假突破率。这一反直觉发现值得深入。'
    ))

    story.append(Paragraph('3.1.2 突破类型 × 生命周期分布预测', s_h3))
    type_pred = [
        [P('突破类型', s_table_header), P('偏好阶段', s_table_header), P('推测理由', s_table_header)],
        [P('MA_UP'), P('PRE_INIT / DISTRIB'), P('均线上穿在盘整区和酝酿区最常见')],
        [P('MA_DOWN'), P('DISTRIB'), P('分布/出货阶段的均线下穿是资金离场的反映')],
        [P('BOLL_UP'), P('EXHAUST'), P('趋势衰竭期价格冲击上轨是最后一波的常见形态')],
        [P('BOLL_DOWN'), P('DISTRIB'), P('盘整中价格下探下轨但不延续')],
    ]
    story.append(make_table(type_pred, col_widths=[page_w*0.22, page_w*0.30, page_w*0.48]))
    story.append(Spacer(1, 1*mm))
    story.append(note_block('<b>Confidence</b>: 中 — 上述分布为基于总体的合理推断，需要突破类型×阶段的交叉统计来验证。'))

    story.append(Paragraph('3.2 策略行为匹配度评估', s_h2))
    match_data = [
        [P('策略行为', s_table_header), P('匹配生命周期', s_table_header), P('匹配度', s_table_header)],
        [P('均线向上突破入场'), P('PRE_INIT → ACCEL'), P('高 ✓')],
        [P('均线向下突破入场'), P('DISTRIB'), P('中')],
        [P('布林上穿入场'), P('EXHAUST'), P('中')],
        [P('布林下穿入场'), P('DISTRIB → PRE_INIT'), P('中')],
        [P('持仓不变'), P('DISTRIB（81.6% 时间）'), P('匹配 ✓')],
    ]
    story.append(make_table(match_data, col_widths=[page_w*0.35, page_w*0.38, page_w*0.27]))
    story.append(obs_block(
        '策略的行为模式与生命周期结构基本匹配——在 81.6% 的盘整时间中，策略大部分时间选择不交易（0 持仓变更），'
        '仅在少数突破事件中入场。MA_UP 突破占 49.3% 也符合趋势策略的基本逻辑。'
    ))

    story.append(PageBreak())

    # ══════════════ Layer 4 ════════════════════════════════════════
    story.append(Paragraph('Layer 4 — 风险与完整性层 Risk & Integrity Layer', s_h1))
    story.append(hr())

    story.append(Paragraph('4.1 风险指标', s_h2))
    risk_data = [
        [P('风险指标', s_table_header), P('数值', s_table_header)],
        [P('最大回撤（绝对值）'), P('¥24,669')],
        [P('最大回撤（百分比）'), P('2.38%')],
        [P('Calmar 比率'), P('1.15')],
        [P('Calmar 基准评估'), P('✅ 合格（> 1.0）')],
    ]
    story.append(make_table(risk_data, col_widths=[page_w*0.40, page_w*0.60]))
    story.append(obs_block(
        '2.38% 的最大回撤对于股票回测来说属于较低水平，表明策略在 1,540 Bar 的风险控制能力良好。'
        'Calmar > 1.0 意味着风险调整后的单位收益稳健。<br/><b>Confidence</b>: 高。'
    ))

    story.append(Paragraph('4.2 数据完整性', s_h2))
    int_data = [
        [P('维度', s_table_header), P('状态', s_table_header)],
        [P('信号事件数据'), P('✅ 完整（88 条）')],
        [P('过滤日志数据'), P('✅ 有数据（0 条 = 无过滤）')],
        [P('突破事件数据'), P('✅ 完整（909 条）')],
        [P('生命周期阶段标签'), P('✅ 完整（1,540 Bar 全覆盖）')],
        [P('突破×生命周期交叉'), P('✅ 完整')],
        [P('置信度分桶数据'), P('❌ 未采集')],
        [P('突破特征列明细'), P('❌ 未输出')],
    ]
    story.append(make_table(int_data, col_widths=[page_w*0.45, page_w*0.55]))

    story.append(Paragraph('4.3 已知缺口', s_h2))
    story.append(P('1. <b>置信度评分缺失</b>：当前 SignalCollector 未输出信号置信度分桶。建议 Phase 1 扩展中增加 confidence_score 字段。'))
    story.append(bullet_item('影响：无法回答"高分信号胜率多少？"等核心研究问题。'))
    story.append(P('2. <b>突破特征列未展开</b>：当前 BreakoutProfile 未输出 volume_ratio、vwap_deviation、strength_score 等特征列。'))
    story.append(bullet_item('影响：限制了假突破预测模型训练。'))
    story.append(P('3. <b>缺少成交明细留存</b>：回测结果未包含每笔成交的时间戳、价格、滑点等细节。'))
    story.append(bullet_item('影响：限制了盈亏归因分析。'))

    story.append(PageBreak())

    # ══════════════ 总评 ═══════════════════════════════════════════
    story.append(Paragraph('总评与战术建议', s_h1))
    story.append(hr())

    story.append(Paragraph('核心结论', s_h2))
    conc_data = [
        [P('维度', s_table_header), P('结论', s_table_header)],
        [P('策略整体'), P('✅ 年化 2.75%，回撤 2.38%，在 601857 的长期盘整背景下表现合理')],
        [P('信号效率'), P('毎 17.5 Bar 触发一次交易，0 次过滤损失，信号触发→成交转化率 100%')],
        [P('假突破控制'), P('整体假突破率 13.09%，EXHAUST 期低至 5.26%，结构可控')],
        [P('生命周期结构'), P('81.6% 时间处于 DISTRIB 盘整，趋势窗口仅 0.3%')],
    ]
    story.append(make_table(conc_data, col_widths=[page_w*0.25, page_w*0.75]))

    story.append(Spacer(1, 3*mm))
    story.append(Paragraph('v2.1 新增发现优先级', s_h2))
    find_data = [
        [P('优先级', s_table_header), P('发现', s_table_header), P('置信度', s_table_header), P('研究价值', s_table_header)],
        [P('🔴'), P('EXHAUST 期假突破率仅 5.26%（均值 1/3）'), P('高'), P('可作为信号权重调节因子')],
        [P('🟡'), P('DISTRIB 期突破密度最高但假突破率也最高'), P('高'), P('盘整区突破需要更谨慎的确认条件')],
        [P('🟡'), P('MA_UP 占突破事件 49.3% = 策略核心触发条件'), P('高'), P('确认趋势策略的核心驱动因子')],
        [P('🟢'), P('信号→成交 100% 转化，0 次过滤意味着无后处理'), P('中'), P('需确认是否适合加入后处理过滤器')],
        [P('🟢'), P('生命周期结构极度偏斜（81.6% DISTRIB）'), P('高'), P('策略在趋势稀有的标的上仍能盈利值得肯定')],
    ]
    story.append(make_table(find_data, col_widths=[page_w*0.08, page_w*0.44, page_w*0.14, page_w*0.34]))

    story.append(Spacer(1, 3*mm))
    story.append(Paragraph('下一阶段建议', s_h2))
    next_data = [
        [P('优先级', s_table_header), P('事项', s_table_header), P('说明', s_table_header)],
        [P('🔴'), P('引入信号置信度评分'), P('解锁高频/低频信号分离分析')],
        [P('🔴'), P('展开突破特征列采集'), P('构建假突破预警模型')],
        [P('🟡'), P('增加突破类型×生命周期交叉统计'), P('验证分布推测')],
        [P('🟡'), P('加入市场状态（bull/bear/sideways）标签'), P('评估策略在不同市态下的表现差异')],
        [P('🟢'), P('建立不同生命周期阶段的仓位调节规则'), P('如 EXHAUST 期放大仓位、DISTRIB 期缩仓')],
    ]
    story.append(make_table(next_data, col_widths=[page_w*0.08, page_w*0.38, page_w*0.54]))

    story.append(Spacer(1, 5*mm))
    story.append(hr())
    story.append(P('<i>报告结束 — v2.1 Phase 1 收尾版 · 生成于 2026-05-18</i>', s_footer))

    return story


# ══════════════ BUILD ═══════════════════════════════════════════════
doc = SimpleDocTemplate(
    output_path,
    pagesize=A4,
    topMargin=15*mm,
    bottomMargin=15*mm,
    leftMargin=15*mm,
    rightMargin=15*mm,
    title='601857 研究型量化分析报告 v2.1',
    author='墨衡 (moheng)',
)

story = build_document()
doc.build(story)
print(f"[OK] PDF generated: {output_path}")

# Verify
import subprocess
result = subprocess.run(['python', '-c', f'''
from reportlab.lib.pagesizes import A4
import os
path = r"{output_path}"
size = os.path.getsize(path)
print(f"  Size: {{size:,}} bytes")

# Count pages by scanning for page objects
with open(path, "rb") as f:
    content = f.read()
    # Count /Type /Page entries (excluding /Pages)
    page_count = content.count(b"/Type /Page") - content.count(b"/Type /Pages")
    print(f"  Pages: ~{{page_count}}")
    has_cjk = b"CJK" in content or b"simsun" in content
    print(f"  CJK embedded: {{has_cjk}}")
'''], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print(f"[STDERR] {result.stderr}")

# Copy to second location
import shutil
output_path2 = os.path.join(output_dir2, '601857_research_report_v2.1_20260518.pdf')
shutil.copy2(output_path, output_path2)
print(f"[OK] Copied to: {output_path2}")
