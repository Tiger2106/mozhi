"""
生成601857研究型量化分析报告v2.1 PDF
使用 reportlab 4.5.1 + SimSun/SimHei 中文字体
"""
import os, sys
sys.path.insert(0, r'C:\Users\17699\mozhi_platform')
os.chdir(r'C:\Users\17699\mozhi_platform')

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable
)
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ─── 注册中文字体 ───────────────────────────
TTF_SEARCH = [
    (r'C:\Windows\Fonts\simsun.ttc', 'SimSun'),
    (r'C:\Windows\Fonts\simhei.ttf', 'SimHei'),
]
CJK = None
for fp, name in TTF_SEARCH:
    if os.path.exists(fp):
        try:
            pdfmetrics.registerFont(TTFont('CJK', fp))
            CJK = 'CJK'
            print(f"字体注册: {fp}")
            break
        except Exception as e:
            print(f"字体 {fp} 注册失败: {e}")

if not CJK:
    CJK = 'Helvetica'
    print("⚠️ 无中文字体，使用 Helvetica")

OUT = r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf'
OUT2 = r'C:\Users\17699\.openclaw\workspace-mochen\reports\pdf\601857_research_report_v2.1_20260518.pdf'

W, H = A4  # 595.27 x 841.89 pt
LM, RM, TM, BM = 50, 50, 50, 50  # margins

def S(name, **kw):
    """快捷创建 ParagraphStyle"""
    base = {
        'fontName': CJK,
        'fontSize': kw.pop('fontSize', 11),
        'leading': kw.pop('leading', 16),
        'spaceAfter': kw.pop('spaceAfter', 6),
        'alignment': kw.pop('alignment', TA_LEFT),
    }
    base.update(kw)
    return ParagraphStyle(name, **base)

title_style = S('title', fontSize=22, leading=30, alignment=TA_CENTER, spaceAfter=4)
subtitle_style = S('subtitle', fontSize=12, leading=18, alignment=TA_CENTER, spaceAfter=20)
h1_style = S('h1', fontSize=16, leading=24, spaceAfter=8, spaceBefore=16)
h2_style = S('h2', fontSize=13, leading=19, spaceAfter=6, spaceBefore=12, alignment=TA_LEFT)
body_style = S('body', fontSize=10, leading=15, spaceAfter=4)
caption_style = S('caption', fontSize=9, leading=13, spaceAfter=2, textColor=colors.grey)
highlight_style = S('highlight', fontSize=10, leading=15, spaceAfter=4, textColor=colors.HexColor('#1a5276'))

def tbl(data, col_widths=None, header=True):
    """生成带格式的表格"""
    w = W - LM - RM
    if col_widths is None:
        n = len(data[0])
        col_widths = [w / n] * n
    t = Table(data, colWidths=col_widths, hAlign='LEFT')
    style_cmds = [
        ('FONTNAME', (0, 0), (-1, -1), CJK),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('LEADING', (0, 0), (-1, -1), 13),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cccccc')),
    ]
    if header:
        style_cmds += [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
        ]
    # 隔行背景色
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f5f5f5')))
    t.setStyle(TableStyle(style_cmds))
    return t

# ─── 构建文档 ─────────────────────────────────
story = []

# 封面
story.append(Spacer(1, 60))
story.append(HRFlowable(width="100%", thickness=4, color=colors.HexColor('#2c3e50')))
story.append(Spacer(1, 30))
story.append(Paragraph("601857 研究型量化分析报告", title_style))
story.append(Paragraph("版本 v2.1", subtitle_style))
story.append(Spacer(1, 15))
story.append(Paragraph("2026-05-18", S('date', fontSize=11, alignment=TA_CENTER, textColor=colors.grey)))
story.append(Spacer(1, 10))
story.append(Paragraph("墨枢 · 墨家投资室", S('date', fontSize=10, alignment=TA_CENTER, textColor=colors.grey)))
story.append(Spacer(1, 30))
story.append(HRFlowable(width="100%", thickness=4, color=colors.HexColor('#2c3e50')))
story.append(Spacer(1, 40))

# 摘要
story.append(Paragraph("报告摘要", h1_style))
story.append(Paragraph(
    "本报告覆盖 Signal Collector / Breakout Profile / Trend Lifecycle / "
    "Conditional Return Matrix / Capital Efficiency / Signal Decay / "
    "Fake Breakout Classifier 等模块的综合分析。全四层结构（结果-行为-结构-研究）持续深化。",
    body_style))
story.append(Spacer(1, 8))

# 数据概览卡
card_data = [
    ['指标', '值', '指标', '值'],
    ['总交易日', '1,540', '总收益', '18.16%'],
    ['年化收益率', '2.75%', '夏普比率', '0.76'],
    ['最大回撤', '2.38%', 'Calmar', '1.15'],
    ['总成交笔数', '88', '胜率', '54.5%'],
]
story.append(tbl(card_data, col_widths=[80, 100, 80, 100]))
story.append(Spacer(1, 8))

story.append(PageBreak())

# ═══ Layer 1：结果层 ════════════════════════
story.append(Paragraph("Layer 1 · 结果层", h1_style))
story.append(Paragraph("收益表现与风险指标", h2_style))

l1_data = [
    ['指标', '值', '说明'],
    ['累计收益率', '18.16%', '1,540个交易日总回报'],
    ['年化收益率', '2.75%', '按252交易日年化'],
    ['最大回撤', '2.38%', '回撤期间最严重损失'],
    ['夏普比率', '0.76', '风险调整后收益'],
    ['卡玛比率', '1.15', '年化/最大回撤'],
    ['总成交', '88笔', '配对后44笔完整交易'],
    ['平均持仓', '9.8天', '策略平均持仓周期'],
]
story.append(tbl(l1_data, col_widths=[100, 100, 200]))
story.append(Spacer(1, 12))

# ═══ Layer 2：行为层 ════════════════════════
story.append(Paragraph("Layer 2 · 行为层", h1_style))
story.append(Paragraph("信号分布与条件收益", h2_style))

# 2.1 信号事件
story.append(Paragraph("2.1 信号事件采集", h2_style))
sig_data = [
    ['维度', '数值'],
    ['信号触发率', '5.71%（88/1,540日）'],
    ['信号→成交转化率', '100%'],
    ['过滤次数', '0次（过滤日志未启用）'],
]
story.append(tbl(sig_data, col_widths=[180, 220]))
story.append(Spacer(1, 8))

# 2.2 条件收益矩阵
story.append(Paragraph("2.2 条件收益矩阵", h2_style))
crm_data = [
    ['条件', '笔数', '胜率', '平均收益', 'Sharpe'],
    ['HIGH (≥0.8)', '3', '66.7%', '+4.58%', '0.45'],
    ['MEDIUM (0.6-0.8)', '19', '57.9%', '+2.19%', '0.51'],
    ['LOW (<0.6)', '22', '45.5%', '+1.80%', '0.30'],
    ['≤5天持仓', '16', '37.5%', '+1.12%', '0.36'],
    ['6~15天持仓', '18', '61.1%', '+2.35%', '0.51'],
    ['>15天持仓', '10', '60.0%', '+3.32%', '0.48'],
]
story.append(tbl(crm_data, col_widths=[130, 60, 70, 80, 60]))
story.append(Spacer(1, 4))

story.append(Paragraph(
    "<b>最佳条件组合</b>：MEDIUM × TREND_UP → Sharpe 0.62，12笔交易，胜率58.3%",
    highlight_style))
story.append(Paragraph(
    "<b>应规避组合</b>：LOW × RANGE → 胜率33.3%，平均收益+0.36%",
    highlight_style))
story.append(Spacer(1, 8))

# 2.3 资本效率
story.append(Paragraph("2.3 资本效率", h2_style))
cap_data = [
    ['指标', '数值'],
    ['资金利用率', '27.9%（~430天持仓 / 1,540天）'],
    ['闲置率', '72.1%'],
    ['平均持仓周期', '9.8天'],
    ['解读', '趋势跟踪策略典型特征，多标并行可改善闲置'],
]
story.append(tbl(cap_data, col_widths=[130, 270]))
story.append(Spacer(1, 8))

# 2.4 信号衰减
story.append(Paragraph("2.4 信号衰减分析", h2_style))
story.append(Paragraph(
    "信号有效半衰期分析：信号生成后延迟天数与收益呈负相关。"
    "指数模型半衰期约5.6天，线性模型约10天。"
    "延迟≤10天可维持≥50%胜率。",
    body_style))

story.append(PageBreak())

# ═══ Layer 3：结构层 ════════════════════════
story.append(Paragraph("Layer 3 · 结构层", h1_style))
story.append(Paragraph("突破画像与趋势生命周期", h2_style))

# 3.1 突破事件
story.append(Paragraph("3.1 假突破画像", h2_style))
brk_data = [
    ['突破类型', '数量', '占比', '假突破数', '假突破率'],
    ['MA_UP', '448', '49.3%', '58', '12.9%'],
    ['MA_DOWN', '258', '28.4%', '33', '12.8%'],
    ['BOLL_UP', '140', '15.4%', '18', '12.9%'],
    ['BOLL_DOWN', '63', '6.9%', '10', '15.9%'],
    ['合计', '909', '100%', '119', '13.09%'],
]
story.append(tbl(brk_data, col_widths=[90, 70, 60, 70, 70]))
story.append(Spacer(1, 4))

# 3.2 生命周期
story.append(Paragraph("3.2 趋势生命周期阶段分布", h2_style))
life_data = [
    ['阶段', 'Bar数', '占比', 'TQ', '区间回报'],
    ['PRE_INIT（准备期）', '324', '16.3%', '0.43', '-21.64%'],
    ['INIT（启动期）', '7', '0.4%', '0.47', '+6.48%'],
    ['MAIN（主升期）', '39', '2.0%', '0.65', '+4.84%'],
    ['EXHAUST（衰竭期）', '1,170', '81.6%', '0.40', '+198.96%'],
    ['DISTRIB（分配期）', '0', '0%', '—', '—'],
]
story.append(tbl(life_data, col_widths=[130, 60, 60, 50, 80]))
story.append(Spacer(1, 8))

# 3.3 假突破 × 生命周期
story.append(Paragraph("3.3 假突破 × 生命周期协同分析", h2_style))
syn_data = [
    ['阶段', '假突破率', '突破密度'],
    ['EXHAUST', '5.26%', '0.30/bar'],
    ['DISTRIB', '13.56%', '0.43/bar'],
    ['PRE_INIT', '11.68%', '0.38/bar'],
]
story.append(tbl(syn_data, col_widths=[100, 100, 100]))
story.append(Spacer(1, 4))
story.append(Paragraph(
    "<b>核心发现</b>：EXHAUST期假突破率仅5.26%，全周期最低——"
    "此阶段产生的突破信号可信度最高。DISTRIB期假突破率13.56%最高。",
    highlight_style))
story.append(Spacer(1, 8))

# 3.4 假突破分类器
story.append(Paragraph("3.4 假突破分类器（规则引擎）", h2_style))
clf_data = [
    ['维度', '权重', '评分逻辑'],
    ['VolumeSupport', '30%', '突破日成交量 / 20日均量'],
    ['TrendAlignment', '25%', '突破方向与趋势方向一致性'],
    ['MomentumQuality', '20%', '突破前N日动量斜率'],
    ['SupportResistance', '15%', '突破价与支撑/阻力位距离'],
    ['VolatilityContext', '10%', '波动率百分位（倒U形评分）'],
]
story.append(tbl(clf_data, col_widths=[140, 70, 190]))
story.append(Spacer(1, 4))
story.append(Paragraph(
    "输出：5档标签 (REAL/PROBABLY_REAL/UNCERTAIN/PROBABLY_FAKE/FAKE)，"
    "基于加权总分判定。",
    body_style))

story.append(PageBreak())

# ═══ Layer 4：研究层 ════════════════════════
story.append(Paragraph("Layer 4 · 研究层", h1_style))
story.append(Paragraph("深度分析与策略建议", h2_style))

story.append(Paragraph("4.1 多标并行框架", h2_style))
story.append(Paragraph(
    "MultiInstrumentEngine已上线（16测试），支持2~3标的并行回测。"
    "CapitalPoolAllocator提供四种资金分配模式（等分/信号加权/风险平价/动量），"
    "CrossSectionReport生成标准化横截面对比表。",
    body_style))
story.append(Spacer(1, 8))

story.append(Paragraph("4.2 知识沉淀", h2_style))
story.append(Paragraph(
    "8条知识条目已写入 knowledge.db，覆盖 Breakout/Lifecycle/Signal/Capital 四类，"
    "全部 confidence=high。实现研究→知识闭环。",
    body_style))
story.append(Spacer(1, 8))

story.append(Paragraph("4.3 综合评估", h2_style))
eval_data = [
    ['维度', '评分', '解读'],
    ['收益质量', '★★★☆☆', '年化2.75%偏低但回撤仅2.38%'],
    ['风险控制', '★★★★☆', '最大回撤2.38%极低，Calmar 1.15'],
    ['结构深度', '★★★★☆', '突破+生命周期+条件矩阵多层分析'],
    ['可扩展性', '★★★☆☆', '多标框架已就绪，需实盘验证'],
]
story.append(tbl(eval_data, col_widths=[100, 80, 220]))
story.append(Spacer(1, 12))

story.append(Paragraph("4.4 风险提示", h2_style))
risks = [
    "1. 回测时间有限单标（601857），多标表现待验证",
    "2. 年化2.75%偏低，趋势跟踪策略在盘整期表现较弱",
    "3. 资金利用率仅27.9%，闲置期需要策略补充",
    "4. 过滤日志尚未启用，风险管理存在盲区",
    "5. 回测数据为前复权价格，实盘滑点和冲击成本未计入",
    "6. 假突破分类器为规则引擎，无ML模型自学习能力",
]
for r in risks:
    story.append(Paragraph(r, body_style))

story.append(Spacer(1, 20))
story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cccccc')))
story.append(Spacer(1, 10))
story.append(Paragraph("墨枢 · 墨家投资室 · 2026-05-18", S('footer', fontSize=8, alignment=TA_CENTER, textColor=colors.grey)))

# ─── 构建 PDF ─────────────────────────────────
def add_page_number(canvas, doc):
    """页脚页码"""
    canvas.saveState()
    canvas.setFont(CJK, 8)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(W / 2, 20, f"— {doc.page} —")
    canvas.restoreState()

doc = SimpleDocTemplate(OUT, pagesize=A4,
                        leftMargin=LM, rightMargin=RM,
                        topMargin=TM, bottomMargin=BM)
doc.build(story, onFirstPage=add_page_number, onLaterPages=add_page_number)

# ─── 验证 ─────────────────────────────────────
import fitz  # PyMuPDF
pdf = fitz.open(OUT)
pages = pdf.page_count
print(f"\n✅ PDF生成: {OUT}")
print(f"   页数: {pages}")
for i, page in enumerate(pdf):
    text = page.get_text()
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text[:200])
    print(f"   第{i+1}页: {len(text)}字符, {'含中文' if has_chinese else '⚠️ 无中文'} (前200: {text[:80].strip()})")
pdf.close()

# 复制到 mochen workspace
import shutil
os.makedirs(os.path.dirname(OUT2), exist_ok=True)
shutil.copy2(OUT, OUT2)
print(f"✅ 已复制: {OUT2}")

# 文件大小
size = os.path.getsize(OUT)
print(f"   文件大小: {size:,} B ({size/1024:.1f} KB)")
