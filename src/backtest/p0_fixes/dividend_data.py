"""
分红引擎 DataLayer — 预加载缓存模块
======================================
职责:
  1. 预加载股息日历到内存 Dict (O(1) 查询)
  2. is_dividend_date(symbol, date) - 判断是否除息日
  3. get_dividend_per_share(symbol, date) - 获取每股现金分红(元)
  4. 双路径: adj_factor 检测除息日 + 外部数据源精确金额

数据流:
  adj_factor 跳变 > 0.1% → 判定为除息事件
  adj_factor 跳变 > 20% → 判定为送转股事件(金额不确定)
  外部数据源优先于 adj_factor 推算

作者: moheng
版本: v1.0 (引擎集成 Stage 1)
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
import os
import json
import sqlite3
import logging

logger = logging.getLogger(__name__)

# 常数
ADJ_FACTOR_DIVIDEND_THRESHOLD = 0.001   # 0.1% 检测分红
ADJ_FACTOR_SPLIT_THRESHOLD = 0.20       # 20% 以上判定为送转股
EXTERNAL_DIV_DIR = os.environ.get(
    "FX_DIV_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "dividends")
)


class DividendCalendar:
    """分红日历 - 预加载缓存实现
    
    按需懒加载，首次查询标的时从两种数据源构建缓存：
    路径 A: 外部数据源 JSON (优先级高)
    路径 B: adj_factor 变化检测 (兜底)
    
    O(1) 查询复杂度: is_dividend_date O(1), get_dividend_per_share O(1)
    """
    
    def __init__(self, db_path: Optional[str] = None):
        self._cache: Dict[str, Dict[str, Dict]] = {}  # symbol -> {date_str -> info}
        self._db_path = db_path
        self._loaded_symbols: set = set()
    
    def _ensure_loaded(self, symbol: str) -> None:
        """确保标的的缓存已加载（按需懒加载）"""
        if symbol in self._loaded_symbols:
            return
        
        events: Dict[str, Dict] = {}
        
        # 路径 A: 外部数据源
        ext_path = os.path.join(EXTERNAL_DIV_DIR, f"{symbol}.json")
        if os.path.exists(ext_path):
            try:
                with open(ext_path, encoding="utf-8") as f:
                    ext_events = json.load(f)
                    for date_str, info in ext_events.items():
                        events[date_str] = info
                        events[date_str]["source"] = "external"
            except Exception as e:
                logger.warning(f"外部分红数据读取失败 {ext_path}: {e}")
        
        # 路径 B: adj_factor 变化检测
        adj_events = self._detect_from_adj_factor(symbol)
        for date_str, info in adj_events.items():
            if date_str not in events:
                # 外部数据不存在时，使用 adj_factor 检测结果
                events[date_str] = info
                events[date_str]["source"] = "adj_factor"
            else:
                # 外部已存在，验证一致性
                ext_dps = events[date_str].get("cash_dividend_per_share", 0)
                adj_dps = info.get("cash_dividend_per_share", 0)
                if ext_dps == 0 and adj_dps == 0:
                    # 两者都无精确金额，标记
                    events[date_str]["note"] = "金额未知"
                elif ext_dps == 0 and adj_dps > 0:
                    # 外部缺少金额但 adj_factor 有值 — 保留 adj_factor 但 WARN
                    events[date_str]["cash_dividend_per_share"] = adj_dps
                    events[date_str]["note"] = "adj_factor推算(外部无数据)"
                elif ext_dps > 0:
                    # 外部数据有金额，保留外部值
                    pass  # 已存在 ext_dps
        
        self._cache[symbol] = events
        self._loaded_symbols.add(symbol)
    
    def _detect_from_adj_factor(self, symbol: str) -> Dict[str, Dict]:
        """路径 B: 通过 adj_factor 跳变检测除息日
        
        从 market_data.db 读取 stock_daily 表，计算 adj_factor 相邻比值。
        跳变 > 0.1% 判断为分红事件，> 20% 为送转股。
        """
        events: Dict[str, Dict] = {}
        
        if self._db_path and os.path.exists(self._db_path):
            try:
                # 使用 sqlite3 直连而非 pd.read_sql URI（需要 SQLAlchemy >= 2.0.36）
                conn = sqlite3.connect(self._db_path)
                df = pd.read_sql(
                    "SELECT trade_date, adj_factor FROM stock_daily "
                    "WHERE symbol = ? ORDER BY trade_date",
                    conn,
                    params=[symbol]
                )
                conn.close()
            except Exception as e:
                logger.warning(f"adj_factor 数据读取失败 {self._db_path}: {e}")
                df = pd.DataFrame()
            
            if len(df) > 1:
                adj = df["adj_factor"].values
                dates = df["trade_date"].values
                ratios = adj[1:] / adj[:-1]
                
                for i in range(len(ratios)):
                    # [FIX v1.1 - W1] 双向检测: tushare adj_factor 在除息日上升(ratio>1)
                    # 原逻辑 ratios[i] < (1 - threshold) 仅检测下降，漏检 0.2%~3.9% 的正向跳变
                    if abs(ratios[i] - 1) > ADJ_FACTOR_DIVIDEND_THRESHOLD:
                        date_str = str(dates[i + 1])
                        change_pct = abs(ratios[i] - 1)
                        
                        if change_pct > ADJ_FACTOR_SPLIT_THRESHOLD:
                            events[date_str] = {
                                "cash_dividend_per_share": 0.0,
                                "stock_dividend_per_10": None,
                                "pre_adj_factor": float(adj[i]),
                                "post_adj_factor": float(adj[i + 1]),
                                "source": "adj_factor",
                                "event_type": "split"
                            }
                        else:
                            # adj_factor 变化方向: ratio>1 (上升) 或 ratio<1 (下降)
                            # 精确每股股息金额无法从单一 adj_factor 确定，设为 0 待外部数据填充
                            events[date_str] = {
                                "cash_dividend_per_share": 0.0,
                                "stock_dividend_per_10": 0,
                                "pre_adj_factor": float(adj[i]),
                                "post_adj_factor": float(adj[i + 1]),
                                "source": "adj_factor",
                                "event_type": "dividend",
                                "note": "adj_factor推算 — 精确金额需外部数据源"
                            }
        
        return events
    
    def is_dividend_date(self, symbol: str, date: str) -> bool:
        """判断某日是否为除息日 (O(1))"""
        self._ensure_loaded(symbol)
        return date in self._cache.get(symbol, {})
    
    def get_dividend_per_share(self, symbol: str, date: str) -> float:
        """获取某日每股现金分红 (O(1), 返回元/股)
        
        返回 0 表示:
          - 非除息日
          - 除息日但金额未知(需外部数据源补充)
        """
        self._ensure_loaded(symbol)
        info = self._cache.get(symbol, {}).get(date)
        if info is None:
            return 0.0
        return info.get("cash_dividend_per_share", 0.0)
    
    def get_dividend_info(self, symbol: str, date: str) -> Optional[Dict]:
        """获取完整分红信息"""
        self._ensure_loaded(symbol)
        return self._cache.get(symbol, {}).get(date)
    
    def get_all_dividend_dates(self, symbol: str) -> List[str]:
        """获取标的所有除息日列表"""
        self._ensure_loaded(symbol)
        return sorted(self._cache.get(symbol, {}).keys())
    
    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """清空缓存"""
        if symbol:
            self._cache.pop(symbol, None)
            self._loaded_symbols.discard(symbol)
        else:
            self._cache.clear()
            self._loaded_symbols.clear()
