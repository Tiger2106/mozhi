@echo off
REM 墨枢 每日02:00 运维任务
REM 由 Windows 任务计划程序调度
REM 日志: C:\Users\17699\mozhi_platform\logs\daily_maintenance.log

cd /d "C:\Users\17699\mozhi_platform"
python scripts/daily_maintenance.py --report >> logs\daily_maintenance.log 2>&1
