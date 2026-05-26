# turnover_rate.py
# 墨家投资室 - 换手率计算模块
# author: 墨衡 | date: 2026-05-22
# 版本：v1.0
#
# 公式：turnover_rate = amount / (float_share × 10000 × price)
#   - amount (元)：成交金额
#   - float_share (万股)：流通股本（Tushare daily_basic.float_share）
#   - price (元)：参考价格（默认收盘价，可选 VWAP）
#   - 分母 = float_share × 10000 × price = 流通市值（元）
#
# 使用方式：
#   from calc.turnover_rate import calc_turnover_rate
#   tr = calc_turnover_rate(amount=1_020_000_000, float_share=16192207.78, price=10.68)

from typing import Optional, Union, List, Dict
import logging

logger = logging.getLogger(__name__)


def calc_turnover_rate(
    amount: float,
    float_share: float,
    price: float,
) -> float:
    """
    计算单日换手率。

    Args:
        amount: 成交金额（元）
        float_share: 流通股本（万股）
        price: 参考价格（元/股）

    Returns:
        换手率比率 [0, 1]，超出范围时 clamp。

    Raises:
        ValueError: 输入参数无效时抛出
    """
    _validate_inputs(amount, float_share, price)

    # 流通市值（元）= float_share(万股) × 10000 × price(元/股)
    float_market_value = float_share * 10000.0 * price

    if float_market_value <= 0:
        raise ValueError(
            f"流通市值 <= 0: float_share={float_share}, price={price}"
        )

    tr = amount / float_market_value

    # Clamp 到 [0, 1]（少数特殊情况可能略超或略低）
    return max(0.0, min(1.0, tr))


def calc_turnover_rate_batch(
    records: List[Dict[str, float]],
    amount_key: str = 'amount',
    float_share_key: str = 'float_share',
    price_key: str = 'close',
    output_key: str = 'turnover_rate',
) -> List[Dict[str, float]]:
    """
    批量计算换手率，支持自定义字段名。

    Args:
        records: 字典列表，每条记录需包含amount/float_share/price字段
        amount_key: 成交金额字段名
        float_share_key: 流通股本字段名
        price_key: 价格字段名
        output_key: 结果输出字段名

    Returns:
        增加 turnover_rate 字段后的记录列表
    """
    results = []
    for i, rec in enumerate(records):
        try:
            tr = calc_turnover_rate(
                amount=rec.get(amount_key, 0),
                float_share=rec.get(float_share_key, 0),
                price=rec.get(price_key, 0),
            )
            rec[output_key] = tr
        except (ValueError, TypeError) as e:
            logger.warning("Record #%d: %s", i, e)
            rec[output_key] = None
        results.append(rec)
    return results


def _validate_inputs(amount: float, float_share: float, price: float):
    """输入有效性检查"""
    if amount is None or float_share is None or price is None:
        raise ValueError("amount, float_share, price 均不能为 None")
    if amount < 0:
        raise ValueError(f"amount 不能为负数: {amount}")
    if float_share <= 0:
        raise ValueError(f"float_share 必须 > 0: {float_share}")
    if price <= 0:
        raise ValueError(f"price 必须 > 0: {price}")
