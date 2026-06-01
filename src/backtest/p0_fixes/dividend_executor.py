"""
分红引擎 Executor — 日终分红现金注入
====================================
职责:
  1. 日终遍历持仓，检测除息日
  2. 现金注入: cash += qty * dps
  3. 审计日志持久化 (JSON)

作者: moheng
版本: v1.0 (引擎集成 Stage 1)
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import json
import os
import logging

from .dividend_data import DividendCalendar  # noqa: F401

logger = logging.getLogger(__name__)


class DividendProcessor:
    """分红现金处理器
    
    在回测引擎日终结算时调用 process_dividends(portfolio, date)
    为所有持仓标的注入分红现金。
    """
    
    def __init__(
        self,
        dividend_calendar: DividendCalendar,
        audit_log_dir: Optional[str] = None
    ):
        self._cal = dividend_calendar
        self._audit_log: List[Dict] = []
        self._audit_log_dir = audit_log_dir or os.environ.get(
            "AUDIT_LOG_DIR",
            os.path.join(os.path.dirname(__file__), "..", "..", "data", "audit")
        )
        os.makedirs(self._audit_log_dir, exist_ok=True)
    
    def process_dividends(self, portfolio: Any, date: str) -> float:
        """日终结算 — 注入分红现金
        
        参数:
          portfolio: 投资组合对象（支持 .positions / .holdings / .get_positions()）
          date: 当前日期字符串 (YYYY-MM-DD)
        
        返回: 当日注入的总分红金额
        """
        positions = self._get_positions(portfolio)
        total_dividend = 0.0
        
        for pos in positions:
            symbol = self._get_symbol(pos)
            qty = self._get_quantity(pos)
            
            if qty <= 0:
                continue
            
            if self._cal.is_dividend_date(symbol, date):
                dps = self._cal.get_dividend_per_share(symbol, date)
                cash = qty * dps
                
                if cash > 0:
                    self._inject_cash(portfolio, cash)
                    total_dividend += cash
                    
                    record = {
                        "date": date,
                        "symbol": symbol,
                        "quantity": qty,
                        "dps": dps,
                        "cash": cash,
                        "timestamp": datetime.now().isoformat()
                    }
                    self._audit_log.append(record)
                    
                    logger.info(
                        f"分红注入: {date} {symbol} {qty}股 × {dps:.4f}元 = {cash:.2f}元"
                    )
                else:
                    info = self._cal.get_dividend_info(symbol, date)
                    if info:
                        logger.warning(
                            f"除息日 {date} {symbol} 分红金额未知(需外部数据源)"
                        )
        
        if total_dividend > 0:
            self._save_audit_log(date)
        
        return total_dividend
    
    def _get_positions(self, portfolio) -> List:
        """从投资组合对象中提取持仓列表

        兼容多种 portfolio 接口格式:
        - portfolio.positions (list)
        - portfolio.holdings (list)
        - portfolio.get_positions() (method)
        - 纯 list / 可迭代对象

        Args:
            portfolio: 投资组合对象或持仓列表

        Returns:
            持仓列表，空列表而非 None 以保证链式调用安全
        """
        if hasattr(portfolio, "positions"):
            return portfolio.positions
        elif hasattr(portfolio, "holdings"):
            return portfolio.holdings
        elif hasattr(portfolio, "get_positions"):
            return portfolio.get_positions()
        elif isinstance(portfolio, list):
            return portfolio
        elif hasattr(portfolio, "__iter__"):
            return list(portfolio)
        return []
    
    def _get_symbol(self, position) -> str:
        """从持仓对象中提取证券代码

        兼容多种持仓表示格式:
        - position.symbol (属性)
        - position.code (属性)
        - dict: key 为 "symbol" / "code" / "id"
        - 其他类型: 直接 str() 兜底

        Args:
            position: 持仓对象

        Returns:
            证券代码字符串
        """
        if hasattr(position, "symbol"):
            return position.symbol
        elif hasattr(position, "code"):
            return position.code
        elif isinstance(position, dict):
            return position.get("symbol") or position.get("code") or str(position.get("id", ""))
        return str(position)
    
    def _get_quantity(self, position) -> float:
        """从持仓对象中提取持有数量

        兼容多种持仓表示格式:
        - position.quantity / position.qty (属性)
        - position.shares (属性)
        - dict: key 为 "quantity" / "qty" / "shares"

        Args:
            position: 持仓对象

        Returns:
            持有数量（股数），float 类型
        """
        if hasattr(position, "quantity") or hasattr(position, "qty"):
            return getattr(position, "quantity", getattr(position, "qty", 0))
        elif hasattr(position, "shares"):
            return position.shares
        elif isinstance(position, dict):
            return float(position.get("quantity") or position.get("qty") or position.get("shares", 0))
        return 0
    
    def _inject_cash(self, portfolio, amount: float) -> None:
        """向投资组合对象注入分红现金

        兼容多种 portfolio 现金属性格式。注入前的现金余额
        由回测引擎的日终结算流程管理，本方法仅执行加法操作。

        Args:
            portfolio: 投资组合对象，支持 .cash / ._cash 属性或 dict['cash']
            amount: 注入现金金额（元），由调用方保证为正数

        Raises:
            不主动抛出异常。不支持的类型（非 dict、无 cash 属性）静默忽略。
        """
        if hasattr(portfolio, "cash"):
            portfolio.cash += amount
        elif hasattr(portfolio, "_cash"):
            portfolio._cash += amount
        elif isinstance(portfolio, dict):
            portfolio["cash"] = portfolio.get("cash", 0) + amount
    
    def _save_audit_log(self, date: str) -> None:
        """将审计日志持久化到磁盘 JSON 文件

        每次 process_dividends 产生分红注入后调用。
        文件路径: {audit_log_dir}/dividend_audit_{date}.json

        Args:
            date: 当前日期字符串 (YYYY-MM-DD)，用于文件名

        Note:
            - 覆盖式写入（非追加），每次写入完整审计日志
            - 写入异常被捕获并记录 logger.error，不向上传播
        """
        log_path = os.path.join(self._audit_log_dir, f"dividend_audit_{date}.json")
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(self._audit_log, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"分红审计日志写入失败: {e}")
    
    def get_audit_log(self, clear: bool = False) -> List[Dict]:
        """获取审计日志"""
        result = list(self._audit_log)
        if clear:
            self._audit_log.clear()
        return result
