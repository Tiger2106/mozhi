import sys, os
sys.path.insert(0, 'src')
from backtest.factors.trend.ma_factor import MAFactor
print("MAFactor available:", MAFactor)
from backtest.factors.volatility.bollinger_factor import BollingerFactor
print("BollingerFactor available:", BollingerFactor)
from backtest.factors.volatility.atr_factor import ATRFactor
print("ATRFactor available:", ATRFactor)
from backtest.factors.trend.macd_factor import MACDFactor
print("MACDFactor available:", MACDFactor)
