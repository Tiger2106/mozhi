# dispatcher.py — 桥接模块，re-export from scheduler.dispatcher
# author: moheng (墨衡)
# created_time: 2026-05-08T23:32+08:00
# 用途：使 automation_v2.paper_trade.dispatcher 可导入

import sys, os
_project_root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), os.pardir, os.pardir)
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from scheduler.dispatcher import *
