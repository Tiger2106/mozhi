"""
fpdf2 生成 601857 研究型量化分析报告 v2.1 PDF
使用 simhei.ttf (TTF单文件，兼容性更好)
输出到不同文件名（旧版本被其他进程锁定）
"""
import os, re, shutil
from fpdf import FPDF

FONT_PATH = r'C:\Windows\Fonts\simhei.ttf'
OUT = r'C:\Users\17699\mozhi_platform\reports\pdf\601857_research_report_v2.1_20260518.pdf'
OUT2 = r'C:\Users\17699\.openclaw\workspace-mochen\reports\pdf\601857_research_report_v2.1_20260518.pdf'

os.makedirs(os.path.dirname(OUT), exist_ok=True)

class ReportPDF(FPDF):
    def header(self):
        self.set_font('CJK', '', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 8, '601857 | 墨枢 · 墨家投资室 | 2026-05-18', align='R')

    def footer(self):
        self.set_y(-15)
        self.set_font('CJK', '', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'\u2014 {self.page_no()} \u2014', align='C')

    def section_title(self, title):
        self.set_font('CJK', '', 16)
        self.set_text_color(44, 62, 80)
        self.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(44, 62, 80)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)

    def subsection(self, title):
        self.set_font('CJK', '', 12)
        self.set_text_color(52, 73, 94)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body(self, text):
        self.set_font('CJK', '', 10)
        self.set_text_color(33, 33, 33)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def highlight(self, text):
        self.set_font('CJK', '', 10)
        self.set_text_color(26, 82, 118)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def risk(self, text):
        self.set_font('CJK', '', 9)
        self.set_text_color(100, 33, 33)
        self.multi_cell(0, 5, text)
        self.ln(1)

    def table(self, headers, rows, col_widths=None):
        w = self.w - self.l_margin - self.r_margin
        if col_widths is None:
            n = len(headers)
            col_widths = [w / n] * n

        self.set_font('CJK', '', 9)
        self.set_fill_color(44, 62, 80)
        self.set_text_color(255, 255, 255)
        for i, h in enumerate(headers):
            self.cell(col_widths[i], 7, h, border=1, fill=True, align='C')
        self.ln()

        for ri, row in enumerate(rows):
            self.set_fill_color(245, 245, 245) if ri % 2 == 0 else self.set_fill_color(255, 255, 255)
            self.set_text_color(33, 33, 33)
            for i, cell in enumerate(row):
                self.cell(col_widths[i], 6, str(cell), border=1, fill=True, align='C' if i > 0 else 'L')
            self.ln()
        self.ln(3)


pdf = ReportPDF(orientation='P', unit='mm', format='A4')
pdf.set_auto_page_break(auto=True, margin=20)
pdf.add_font('CJK', '', FONT_PATH)
pdf.add_page()

# ═══ 封面 ════════════════════════════════════
pdf.ln(30)
pdf.set_font('CJK', '', 24)
pdf.set_text_color(44, 62, 80)
pdf.cell(0, 15, '601857 研究型量化分析报告', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(5)
pdf.set_font('CJK', '', 14)
pdf.set_text_color(100, 100, 100)
pdf.cell(0, 10, '版本 v2.1', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(10)
pdf.set_font('CJK', '', 11)
pdf.cell(0, 8, '2026-05-18', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.cell(0, 8, '墨枢 · 墨家投资室', align='C', new_x="LMARGIN", new_y="NEXT")
pdf.ln(20)
pdf.set_draw_color(44, 62, 80)
pdf.set_line_width(0.5)
pdf.line(30, pdf.get_y(), pdf.w - 30, pdf.get_y())
pdf.ln(15)

# ═══ 摘要 ════════════════════════════════════
pdf.section_title('报告摘要')
pdf.body(
    '本报告覆盖Signal Collector / Breakout Profile / Trend Lifecycle / '
    'Conditional Return Matrix / Capital Efficiency / Signal Decay / '
    'Fake Breakout Classifier等模块的综合分析。全四层结构（结果-行为-结构-研究）持续深化。')
pdf.table(
    ['指标', '值', '指标', '值'],
    [
        ['总交易日', '1,540', '总收益', '18.16%'],
        ['年化收益率', '2.75%', '夏普比率', '0.76'],
        ['最大回撤', '2.38%', 'Calmar', '1.15'],
        ['总成交笔数', '88', '胜率', '54.5%'],
    ],
    col_widths=[40, 50, 40, 50]
)

# ═══ Layer 1 ═════════════════════════════════
pdf.add_page()
pdf.section_title('Layer 1  结果层')
pdf.subsection('收益表现与风险指标')
pdf.table(
    ['指标', '值', '说明'],
    [
        ['累计收益率', '18.16%', '1,540个交易日总回报'],
        ['年化收益率', '2.75%', '按252交易日年化'],
        ['最大回撤', '2.38%', '回撤期间最严重损失'],
        ['夏普比率', '0.76', '风险调整后收益'],
        ['卡玛比率', '1.15', '年化/最大回撤'],
        ['总成交', '88笔', '配对后44笔完整交易'],
        ['平均持仓', '9.8天', '策略平均持仓周期'],
    ],
    col_widths=[50, 50, 90]
)

# ═══ Layer 2 ═════════════════════════════════
pdf.section_title('Layer 2  行为层')
pdf.subsection('2.1 信号事件采集')
pdf.table(
    ['维度', '数值'],
    [
        ['信号触发率', '5.71% (88/1,540日)'],
        ['信号成交转化率', '100%'],
        ['过滤次数', '0次（过滤日志未启用）'],
    ],
    col_widths=[80, 100]
)
pdf.subsection('2.2 条件收益矩阵')
pdf.table(
    ['条件', '笔数', '胜率', '平均收益', 'Sharpe'],
    [
        ['HIGH (>=0.8)', '3', '66.7%', '+4.58%', '0.45'],
        ['MEDIUM (0.6-0.8)', '19', '57.9%', '+2.19%', '0.51'],
        ['LOW (<0.6)', '22', '45.5%', '+1.80%', '0.30'],
        ['<=5天持仓', '16', '37.5%', '+1.12%', '0.36'],
        ['6~15天持仓', '18', '61.1%', '+2.35%', '0.51'],
        ['>15天持仓', '10', '60.0%', '+3.32%', '0.48'],
    ],
    col_widths=[65, 30, 35, 40, 30]
)
pdf.highlight('最佳条件组合: MEDIUM x TREND_UP -> Sharpe 0.62, 12笔, 胜率58.3%')
pdf.highlight('应规避组合: LOW x RANGE -> 胜率33.3%, 平均收益+0.36%')

pdf.subsection('2.3 资本效率')
pdf.table(
    ['指标', '数值'],
    [
        ['资金利用率', '27.9% (~430天持仓 / 1,540天)'],
        ['闲置率', '72.1%'],
        ['平均持仓周期', '9.8天'],
    ],
    col_widths=[70, 120]
)
pdf.body('趋势跟踪策略典型特征: 约72%时间资金闲置, 多标并行可改善利用率。')

pdf.subsection('2.4 信号衰减分析')
pdf.body(
    '信号生成后延迟天数与收益呈负相关。指数模型半衰期约5.6天, '
    '线性模型半衰期约10天。延迟<=10天可维持>=50%胜率。')

# ═══ Layer 3 ═════════════════════════════════
pdf.add_page()
pdf.section_title('Layer 3  结构层')
pdf.subsection('3.1 假突破画像')
pdf.table(
    ['突破类型', '数量', '占比', '假突破数', '假突破率'],
    [
        ['MA_UP', '448', '49.3%', '58', '12.9%'],
        ['MA_DOWN', '258', '28.4%', '33', '12.8%'],
        ['BOLL_UP', '140', '15.4%', '18', '12.9%'],
        ['BOLL_DOWN', '63', '6.9%', '10', '15.9%'],
        ['合计', '909', '100%', '119', '13.09%'],
    ],
    col_widths=[45, 35, 30, 35, 35]
)

pdf.subsection('3.2 趋势生命周期阶段分布')
pdf.table(
    ['阶段', 'Bar数', '占比', 'TQ', '区间回报'],
    [
        ['PRE_INIT (准备期)', '324', '16.3%', '0.43', '-21.64%'],
        ['INIT (启动期)', '7', '0.4%', '0.47', '+6.48%'],
        ['MAIN (主升期)', '39', '2.0%', '0.65', '+4.84%'],
        ['EXHAUST (衰竭期)', '1,170', '81.6%', '0.40', '+198.96%'],
        ['DISTRIB (分配期)', '0', '0%', '--', '--'],
    ],
    col_widths=[65, 30, 30, 25, 40]
)

pdf.subsection('3.3 假突破 x 生命周期协同分析')
pdf.table(
    ['阶段', '假突破率', '突破密度'],
    [
        ['EXHAUST', '5.26%', '0.30/bar'],
        ['DISTRIB', '13.56%', '0.43/bar'],
        ['PRE_INIT', '11.68%', '0.38/bar'],
    ],
    col_widths=[55, 50, 50]
)
pdf.highlight('EXHAUST期假突破率仅5.26%全周期最低, 此阶段信号可信度最高。')

pdf.subsection('3.4 假突破分类器')
pdf.table(
    ['维度', '权重', '评分逻辑'],
    [
        ['VolumeSupport', '30%', '突破日成交量/20日均量'],
        ['TrendAlignment', '25%', '突破方向与趋势方向一致性'],
        ['MomentumQuality', '20%', '突破前N日动量斜率'],
        ['SupportResistance', '15%', '突破价与支撑阻力位距离'],
        ['VolatilityContext', '10%', '波动率百分位-倒U形评分'],
    ],
    col_widths=[70, 35, 90]
)
pdf.body(
    '输出5档标签: REAL / PROBABLY_REAL / UNCERTAIN / PROBABLY_FAKE / FAKE, '
    '基于规则引擎加权总分判定。')

# ═══ Layer 4 ═════════════════════════════════
pdf.add_page()
pdf.section_title('Layer 4  研究层')

pdf.subsection('4.1 多标并行框架')
pdf.body(
    'MultiInstrumentEngine已上线(16测试通过), 支持2-3标的并行回测。'
    'CapitalPoolAllocator提供四种资金分配模式(等分/信号加权/风险平价/动量), '
    'CrossSectionReport生成标准化横截面对比表。')

pdf.subsection('4.2 知识沉淀')
pdf.body(
    '8条知识条目已写入knowledge.db, 覆盖Breakout/Lifecycle/Signal/Capital四类, '
    '全部confidence=high, 实现研究到知识闭环。')

pdf.subsection('4.3 综合评估')
pdf.table(
    ['维度', '评分', '解读'],
    [
        ['收益质量', '***', '年化2.75%偏低但回撤仅2.38%'],
        ['风险控制', '****', '最大回撤2.38%极低, Calmar 1.15'],
        ['结构深度', '****', '突破+生命周期+条件矩阵多层分析'],
        ['可扩展性', '***', '多标框架已就绪, 需实盘验证'],
    ],
    col_widths=[50, 35, 100]
)

pdf.subsection('4.4 风险提示')
risks = [
    '1. 回测时间有限单标(601857), 多标表现待验证',
    '2. 年化2.75%偏低, 趋势跟踪策略在盘整期表现较弱',
    '3. 资金利用率仅27.9%, 闲置期需要策略补充',
    '4. 过滤日志尚未启用, 风险管理存在盲区',
    '5. 回测数据为前复权价格, 实盘滑点和冲击成本未计入',
    '6. 假突破分类器为规则引擎, 无ML模型自学习能力',
]
for r in risks:
    pdf.risk(r)

# ═══ 输出 ════════════════════════════════════
# 写入临时文件, 尝试覆盖目标
TMP = os.path.join(os.path.dirname(OUT), '_tmp_v2.1.pdf')
pdf.output(TMP)
size_kb = os.path.getsize(TMP) / 1024
print(f'Temp PDF: {TMP} ({size_kb:.1f} KB)')

# 验证
with open(TMP, 'rb') as f:
    raw = f.read()
raw_text = raw.decode('latin-1')
pages_count = raw_text.count('/Type /Page') - raw_text.count('/Type /Pages')
tj_count = len(re.findall(r'Tj|TJ', raw_text))
chinese_lines = 0
for line in raw_text.split('\n'):
    for c in line:
        if ord(c) > 127:
            chinese_lines += 1
            break

print(f'Pages: {pages_count}, Text operators: {tj_count}, Lines with CJK: {chinese_lines}')
print(f'SimHei font in PDF: {"simhei" in raw_text.lower() or "SimHei" in raw_text}')
print(f'Valid PDF header: {raw[:8]}')

# 复制到目标（用shutil.copy2, 可能目标被锁但源文件在）
shutil.copy2(TMP, OUT)
print(f'Copied to: {OUT}')

shutil.copy2(TMP, OUT2)
print(f'Copied to: {OUT2}')

os.remove(TMP)
print('DONE')
