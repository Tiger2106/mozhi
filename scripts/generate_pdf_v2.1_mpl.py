"""
matplotlib PdfPages 生成 601857 研究型量化分析报告 v2.1
输出到 workspace-mochen（原路径被锁定）
"""
import os, shutil
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.backends.backend_pdf import PdfPages

FONT_TITLE = FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf', size=22)
FONT_SUB = FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf', size=14)
FONT_H1 = FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf', size=15)
FONT_H2 = FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf', size=12)
FONT_BODY = FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf', size=10)
FONT_SM = FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf', size=9)
FONT_TNY = FontProperties(fname=r'C:\Windows\Fonts\simhei.ttf', size=8)

W, H = 8.27, 11.69  # A4 inch

OUT = r'C:\Users\17699\.openclaw\workspace-mochen\reports\pdf\601857_research_report_v2.1_20260518.pdf'
OUT2 = r'C:\Users\17699\mozhi_platform\reports\pdf\601857_v2.1_report.pdf'

os.makedirs(os.path.dirname(OUT), exist_ok=True)
os.makedirs(os.path.dirname(OUT2), exist_ok=True)


def table(ax, x, y, headers, rows, col_widths):
    rh, hh = 0.25, 0.30
    for ci, h in enumerate(headers):
        cx = x + sum(col_widths[:ci])
        ax.add_patch(plt.Rectangle((cx, y-hh), col_widths[ci], hh, facecolor='#2c3e50', edgecolor='white', lw=0.5))
        ax.text(cx+col_widths[ci]/2, y-hh/2, h, fontproperties=FONT_SM, color='white', ha='center', va='center')
    cur = y - hh
    for ri, row in enumerate(rows):
        bg = '#f5f5f5' if ri%2==0 else 'white'
        for ci, cell in enumerate(row):
            cx = x + sum(col_widths[:ci])
            ax.add_patch(plt.Rectangle((cx, cur-rh), col_widths[ci], rh, facecolor=bg, edgecolor='#ddd', lw=0.3))
            al = 'left' if ci==0 else 'center'
            if al == 'left':
                ax.text(cx+0.04, cur-rh/2, str(cell), fontproperties=FONT_SM, color='#222', ha='left', va='center')
            else:
                ax.text(cx+col_widths[ci]/2, cur-rh/2, str(cell), fontproperties=FONT_SM, color='#222', ha='center', va='center')
        cur -= rh
    return cur


def header_footer(ax, page_num):
    ax.text(W-0.5, H-0.35, '601857 | 墨枢 | 2026-05-18', fontproperties=FONT_TNY, color='#888', ha='right', va='top')
    ax.text(W/2, 0.3, f'-- {page_num} --', fontproperties=FONT_TNY, color='#ccc', ha='center')


with PdfPages(OUT) as pdf:
    # Page 1: Cover
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis('off')
    header_footer(ax, 1)
    ax.text(W/2, 8.5, '601857 研究型量化分析报告', fontproperties=FONT_TITLE, color='#2c3e50', ha='center', va='center')
    ax.text(W/2, 8.0, '版本 v2.1', fontproperties=FONT_SUB, color='#666', ha='center', va='center')
    ax.text(W/2, 7.5, '2026-05-18', fontproperties=FONT_H2, color='#888', ha='center', va='center')
    ax.text(W/2, 7.1, '墨枢 · 墨家投资室', fontproperties=FONT_BODY, color='#888', ha='center', va='center')
    ax.plot([2.0, W-2.0], [6.5, 6.5], color='#2c3e50', lw=2)
    ax.text(0.7, 6.0, '报告摘要', fontproperties=FONT_H1, color='#2c3e50')
    ax.text(0.7, 5.6, '本报告覆盖 Signal Collector / Breakout Profile / Trend Lifecycle /\nConditional Return Matrix / Capital Efficiency / Signal Decay /\nFake Breakout Classifier 等模块的综合分析。全四层结构\n（结果-行为-结构-研究）持续深化。',
            fontproperties=FONT_BODY, color='#333', va='top')
    table(ax, 0.7, 4.8, ['指标','值','指标','值'],
        [['总交易日','1,540','总收益','18.16%'],['年化收益率','2.75%','夏普比率','0.76'],
         ['最大回撤','2.38%','Calmar','1.15'],['总成交笔数','88','胜率','54.5%']],
        col_widths=[1.1,1.4,1.1,1.4])
    pdf.savefig(fig, dpi=200); plt.close(fig)
    print('Page 1 done')

    # Page 2: Layer 1+2
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis('off')
    header_footer(ax, 2)
    y = H - 1.0
    ax.text(0.7, y, 'Layer 1  结果层', fontproperties=FONT_H1, color='#2c3e50'); y -= 0.45
    ax.text(0.7, y, '收益表现与风险指标', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['指标','值','说明'],
        [['累计收益率','18.16%','1,540个交易日总回报'],['年化收益率','2.75%','按252交易日年化'],
         ['最大回撤','2.38%','回撤期间最严重损失'],['夏普比率','0.76','风险调整后收益'],
         ['卡玛比率','1.15','年化/最大回撤'],['总成交','88笔','配对后44笔完整交易'],
         ['平均持仓','9.8天','策略平均持仓周期']], col_widths=[1.5,1.2,2.5]); y -= 0.3
    ax.text(0.7, y, 'Layer 2  行为层', fontproperties=FONT_H1, color='#2c3e50'); y -= 0.45
    ax.text(0.7, y, '2.1 信号事件采集', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['维度','数值'],
        [['信号触发率','5.71% (88/1,540日)'],['信号成交转化率','100%'],['过滤次数','0次(过滤未启用)']],
        col_widths=[2.0,3.2]); y -= 0.2
    ax.text(0.7, y, '2.2 条件收益矩阵', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['条件','笔数','胜率','平均收益','Sharpe'],
        [['HIGH(>=0.8)','3','66.7%','+4.58%','0.45'],['MEDIUM(0.6-0.8)','19','57.9%','+2.19%','0.51'],
         ['LOW(<0.6)','22','45.5%','+1.80%','0.30'],['<=5天','16','37.5%','+1.12%','0.36'],
         ['6~15天','18','61.1%','+2.35%','0.51'],['>15天','10','60.0%','+3.32%','0.48']],
        col_widths=[1.8,0.8,0.8,1.2,0.8]); y -= 0.15
    ax.text(0.7, y, '最佳: MEDIUM x TREND_UP  Sharpe 0.62  12笔  58.3%', fontproperties=FONT_BODY, color='#1a5276'); y -= 0.2
    ax.text(0.7, y, '规避: LOW x RANGE  胜率33.3%  收益+0.36%', fontproperties=FONT_BODY, color='#1a5276'); y -= 0.3
    ax.text(0.7, y, '2.3 资本效率', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['指标','数值'],
        [['资金利用率','27.9% (~430天/1,540天)'],['闲置率','72.1%'],['平均持仓','9.8天']],
        col_widths=[1.8,3.4])
    ax.text(0.7, y-0.15, '趋势跟踪策略特征: 72%资金闲置, 多标并行可改善', fontproperties=FONT_BODY, color='#555')
    pdf.savefig(fig, dpi=200); plt.close(fig)
    print('Page 2 done')

    # Page 3: Layer 3
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis('off')
    header_footer(ax, 3)
    y = H - 1.0
    ax.text(0.7, y, '2.4 信号衰减分析', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    ax.text(0.7, y, '信号延迟天数与收益负相关  指数半衰期5.6天  线性半衰期10天\n延迟<=10天可维持>=50%胜率',
            fontproperties=FONT_BODY, color='#333', va='top'); y -= 0.7
    ax.text(0.7, y, 'Layer 3  结构层', fontproperties=FONT_H1, color='#2c3e50'); y -= 0.45
    ax.text(0.7, y, '3.1 假突破画像', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['突破类型','数量','占比','假突破数','假突破率'],
        [['MA_UP','448','49.3%','58','12.9%'],['MA_DOWN','258','28.4%','33','12.8%'],
         ['BOLL_UP','140','15.4%','18','12.9%'],['BOLL_DOWN','63','6.9%','10','15.9%'],
         ['合计','909','100%','119','13.09%']], col_widths=[1.3,0.8,0.8,1.0,0.9]); y -= 0.2
    ax.text(0.7, y, '3.2 趋势生命周期阶段分布', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['阶段','Bar数','占比','TQ','区间回报'],
        [['PRE_INIT(准备)','324','16.3%','0.43','-21.64%'],['INIT(启动)','7','0.4%','0.47','+6.48%'],
         ['MAIN(主升)','39','2.0%','0.65','+4.84%'],['EXHAUST(衰竭)','1,170','81.6%','0.40','+198.96%'],
         ['DISTRIB(分配)','0','0%','--','--']], col_widths=[1.8,0.7,0.7,0.7,1.0]); y -= 0.2
    ax.text(0.7, y, '3.3 假突破x生命周期协同', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['阶段','假突破率','突破密度'],
        [['EXHAUST','5.26%','0.30/bar'],['DISTRIB','13.56%','0.43/bar'],['PRE_INIT','11.68%','0.38/bar']],
        col_widths=[1.8,1.5,1.5])
    ax.text(0.7, y-0.15, '核心: EXHAUST期假突破率5.26%全周期最低, 信号可信度最高', fontproperties=FONT_BODY, color='#1a5276'); y -= 0.4
    ax.text(0.7, y, '3.4 假突破分类器(规则引擎)', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['维度','权重','评分逻辑'],
        [['VolumeSupport','30%','成交量/20日均量'],['TrendAlignment','25%','方向与趋势一致性'],
         ['MomentumQuality','20%','动量斜率'],['SupportResistance','15%','支撑/阻力距离'],
         ['VolatilityContext','10%','波动率倒U形']], col_widths=[2.0,1.0,2.6])
    ax.text(0.7, y-0.15, '输出5档: REAL / PROBABLY_REAL / UNCERTAIN / PROBABLY_FAKE / FAKE', fontproperties=FONT_BODY, color='#555')
    pdf.savefig(fig, dpi=200); plt.close(fig)
    print('Page 3 done')

    # Page 4: Layer 4
    fig, ax = plt.subplots(figsize=(W, H))
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis('off')
    header_footer(ax, 4)
    y = H - 1.0
    ax.text(0.7, y, 'Layer 4  研究层', fontproperties=FONT_H1, color='#2c3e50'); y -= 0.45
    ax.text(0.7, y, '4.1 多标并行框架', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    ax.text(0.7, y, 'MultiInstrumentEngine已上线(16测试通过)  支持2-3标的并行回测\nCapitalPoolAllocator四种模式(等分/信号加权/风险平价/动量)\nCrossSectionReport生成标准化横截面对比表',
            fontproperties=FONT_BODY, color='#333', va='top'); y -= 0.65
    ax.text(0.7, y, '4.2 知识沉淀', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    ax.text(0.7, y, '8条知识条目写入knowledge.db 覆盖Breakout/Lifecycle/Signal/Capital\n全部confidence=high 实现研究到知识闭环',
            fontproperties=FONT_BODY, color='#333', va='top'); y -= 0.55
    ax.text(0.7, y, '4.3 综合评估', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    y = table(ax, 0.7, y, ['维度','评分','解读'],
        [['收益质量','***','年化2.75%偏低但回撤2.38%'],['风险控制','****','最大回撤2.38%, Calmar 1.15'],
         ['结构深度','****','突破+生命周期+条件矩阵'],['可扩展性','***','多标框架就绪, 待实盘验证']],
        col_widths=[1.2,0.8,2.8]); y -= 0.25
    ax.text(0.7, y, '4.4 风险提示', fontproperties=FONT_H2, color='#34495e'); y -= 0.35
    for r in ['1. 回测单标(601857) 多标表现待验证','2. 年化2.75%偏低 盘整期表现较弱',
              '3. 资金利用率27.9% 闲置期需补充','4. 过滤日志未启用 风险有盲区',
              '5. 前复权价格 实盘滑点未计入','6. 规则引擎 无ML自学习']:
        ax.text(0.7, y, r, fontproperties=FONT_BODY, color='#882222'); y -= 0.22
    ax.text(W/2, 0.5, '墨枢 · 墨家投资室 · 2026-05-18', fontproperties=FONT_TNY, color='#888', ha='center')
    pdf.savefig(fig, dpi=200); plt.close(fig)
    print('Page 4 done')

print(f'\nFinal PDF: {OUT} ({os.path.getsize(OUT)/1024:.1f} KB)')

# Verify with PyMuPDF
import fitz
doc = fitz.open(OUT)
print(f'Pages: {doc.page_count}')
for i in range(doc.page_count):
    pix = doc[i].get_pixmap(dpi=72)
    s = pix.samples
    nw = sum(1 for j in range(0, len(s), 3) if s[j] < 200)
    print(f'  Page {i+1}: {pix.width}x{pix.height} content={100*nw/len(s)*3:.1f}%')
    
    # Render to image for visual check
    img_out = rf'C:\Users\17699\.openclaw\workspace-mochen\reports\pdf\_preview_p{i+1}.png'
    pix.save(img_out)
    print(f'    Preview: {img_out}')
doc.close()

# Copy alternate
try:
    shutil.copy2(OUT, OUT2)
    print(f'Copied: {OUT2}')
except:
    print('Note: copy to mozhi_platform blocked (file locked)')

print('DONE')
