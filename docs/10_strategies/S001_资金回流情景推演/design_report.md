# S001 资金回流情景推演 — 设计报告

**作者**: 墨衡
**创建时间**: 2026-05-25T10:46+08:00
**版本**: v1.0
**状态**: 已批准

---

## 1. 设计目标

构建资金回流情景推演模型，评估A50市场在不同资金回流强度下可能的价格路径。核心为四重折扣因子链 + 蒙特卡洛模拟。

## 2. 四重折扣因子链

### 2.1 因子定义

| 因子 | 符号 | 含义 | 数据来源 |
|:-----|:-----|:------|:---------|
| α₁ | 宏观折扣因子 | 国内货币政策/海外流动性对资金回流意愿的影响 | 宏观指标 + 北向资金净流 |
| α₂ | 行业折扣因子 | 行业景气度对资金偏好度的影响 | 行业ETF资金流 + ROE变化 |
| α₃ | 动量折扣因子 | 市场动量趋势对资金持续性的影响 | 价格动量(12M/3M) |
| α₄ | 结构折扣因子 | 市场微观结构（流动性、波动率）对资金效率的影响 | 买卖价差、换手率 |

### 2.2 因子链计算

```
资金回流强度 = α₁ × α₂ × α₃ × α₄
```

各因子取值域：[0, 1]，1=无折扣（资金完美回流），0=完全阻塞。

### 2.3 因子计算接口

```python
def compute_alpha1(date: str) -> float:
    """宏观折扣因子"""
    pass

def compute_alpha2(symbol: str, date: str) -> float:
    """行业折扣因子"""
    pass

def compute_alpha3(symbol: str, date: str) -> float:
    """动量折扣因子"""
    pass

def compute_alpha4(symbol: str, date: str) -> float:
    """结构折扣因子"""
    pass
```

## 3. 蒙特卡洛模拟

### 3.1 模拟目标

对每只标的，在四因子联合分布上采样，模拟：
1. 资金回流强度的概率分布
2. 价格路径的情景分支
3. 尾部风险量化（5%/95%分位）

### 3.2 模拟骨架

```python
class MonteCarloSimulator:
    def __init__(self, alpha_factors, n_paths=10000):
        pass
    
    def sample_joint_distribution(self):
        """采样四因子的联合分布"""
        pass
    
    def simulate_price_path(self, alpha_t, current_price, volatility):
        """单条价格路径模拟（几何布朗运动 + 因子调整）"""
        pass
    
    def aggregate_results(self):
        """聚合所有路径，输出分位点和情景"""
        pass
```

### 3.3 输出

```json
{
  "meta": {
    "author": "moheng",
    "date": "YYYY-MM-DD",
    "version": "v1",
    "status": "READY"
  },
  "scenarios": [
    {
      "symbol": "601857",
      "scenario": "base_case",
      "probability": 0.60,
      "price_target": 8.50,
      "confidence_interval": [7.80, 9.30]
    },
    {
      "symbol": "601857",
      "scenario": "bull_case",
      "probability": 0.25,
      "price_target": 9.80,
      "confidence_interval": [9.00, 10.50]
    },
    {
      "symbol": "601857",
      "scenario": "bear_case",
      "probability": 0.15,
      "price_target": 7.20,
      "confidence_interval": [6.50, 8.00]
    }
  ]
}
```

## 4. 开发计划

| 里程碑 | 时间 | 产出 |
|:-------|:-----|:-----|
| 初版骨架 | 6/1 | α₁~α₄ 接口占位 + MC模拟骨架 |
| 因子计算实现 | 6/8 | 各因子实际数据接入 |
| 联调测试 | 6/15 | 端到端模拟 + 结果验证 |
| 正式发布 | 6/22 | 纳入每日管线 |
