"""backup_manager — 数据库备份管理（BS-1 / P1-NEW-3）

功能：
  1. 每日收盘后自动备份 trade_engine.db 至 backup/ 目录（日期戳）
  2. 保留最近 30 天备份，自动清理过期（backup_cleanup）
  3. 提供 restore(date) 恢复脚本
  4. 记录备份日志文件

使用方式：
    from utils.backup_manager import BackupManager
    bm = BackupManager()
    bm.run_daily_backup()       # 收盘后调用
    bm.restore(date(2026,5,11)) # 恢复指定日期的备份
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from utils import time_utils
from src.config import SHANGHAI_TZ

logger = logging.getLogger("paper_trade.backup_manager")

# ============================================================
# 常量
# ============================================================

DEFAULT_DB_PATH = "mo_zhi_sharereports/trade_engine.db"
DEFAULT_BACKUP_DIR = "mo_zhi_sharereports/backup"
RETENTION_DAYS = 30
TZ_SHANGHAI = SHANGHAI_TZ


class BackupManager:
    """DB 备份管理器。

    参数：
        db_path — 源数据库文件路径
        backup_dir — 备份目录
        retention_days — 保留天数（默认 30）
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        backup_dir: str = DEFAULT_BACKUP_DIR,
        retention_days: int = RETENTION_DAYS,
    ):
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.retention_days = retention_days
        os.makedirs(backup_dir, exist_ok=True)

    # ----------------------------------------------------------
    # 备份文件名
    # ----------------------------------------------------------

    def backup_filename(self, backup_date: Optional[date] = None) -> str:
        """生成备份文件名：trade_engine_YYYYMMDD.db。"""
        d = backup_date or time_utils.today()
        return f"trade_engine_{d.strftime('%Y%m%d')}.db"

    def backup_filepath(self, backup_date: Optional[date] = None) -> str:
        """生成完整备份路径。"""
        return os.path.join(self.backup_dir, self.backup_filename(backup_date))

    # ----------------------------------------------------------
    # 每日备份
    # ----------------------------------------------------------

    def run_daily_backup(self, backup_date: Optional[date] = None) -> str:
        """每日备份（收盘后调用）。

        参数：
            backup_date — 备份日期（None =当日）

        返回：
            备份文件路径

        前置条件：
            - trade_engine.db 存在
            - backup/ 目录已创建

        操作：
            1. 复制 trade_engine.db → backup/trade_engine_{date}.db
            2. 记录备份日志（写入 backup/backup_log.txt）
            3. 自动清理超过 30 天的旧备份
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"数据库文件不存在: {self.db_path}")

        target_path = self.backup_filepath(backup_date)

        # V1.1-001: WAL checkpoint — 确保全部事务写入主文件后再备份
        try:
            import sqlite3
            chk_conn = sqlite3.connect(self.db_path)
            chk_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            chk_conn.close()
        except Exception:
            pass  # 非WAL模式时忽略

        # 复制
        shutil.copy2(self.db_path, target_path)
        logger.info("备份完成: %s → %s", self.db_path, target_path)

        # 记录日志
        self._log_backup(backup_date)

        # 清理过期
        self.backup_cleanup()

        return target_path

    def _log_backup(self, backup_date: Optional[date] = None) -> None:
        """记录备份日志到 backup/backup_log.txt。"""
        log_path = os.path.join(self.backup_dir, "backup_log.txt")
        d = (backup_date or time_utils.today()).strftime("%Y-%m-%d")
        now_str = time_utils.now().isoformat()
        entry = f"[{now_str}] 备份: trade_engine_{d.replace('-','')}.db\n"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.debug("备份日志已记录: %s", log_path)

    # ----------------------------------------------------------
    # 清理（P1-NEW-3）
    # ----------------------------------------------------------

    def backup_cleanup(self) -> int:
        """清理超过保留期限的旧备份。

        规则：
            - 扫描 backup_dir 下 trade_engine_*.db 文件
            - 删除文件 mtime > retention_days 天的旧文件
            - 记录清理数量

        返回：
            被删除的文件数量
        """
        now = time_utils.now()
        cutoff = now - timedelta(days=self.retention_days)
        pattern = os.path.join(self.backup_dir, "trade_engine_*.db")
        removed = 0

        for filepath in glob.glob(pattern):
            mtime = datetime.fromtimestamp(os.path.getmtime(filepath), tz=TZ_SHANGHAI)
            if mtime < cutoff:
                os.unlink(filepath)
                logger.info("清理旧备份: %s (mtime=%s)", filepath, mtime.strftime("%Y-%m-%d"))
                removed += 1

        if removed > 0:
            logger.info("备份清理完成: 删除 %d 个文件", removed)
        else:
            logger.debug("无过期备份需要清理")

        return removed

    def cleanup(self) -> int:
        """backup_cleanup 的别名，向后兼容。"""
        return self.backup_cleanup()

    # ----------------------------------------------------------
    # 恢复（预留）
    # ----------------------------------------------------------

    def restore(self, restore_date: date) -> Optional[str]:
        """恢复指定日期的备份文件。

        参数：
            restore_date — 要恢复的备份日期

        返回：
            恢复后的备份文件路径，若找不到对应备份则返回 None

        注意：
            - 仅返回备份文件路径，不自动覆盖 trade_engine.db
            - 调用方需自行决定是否覆盖（建议手动确认）
            - 此方法同时将备份文件复制一份到当前目录，
              文件名会追加 _restored 后缀以防止误覆盖
        """
        backup_path = self.backup_filepath(restore_date)
        if not os.path.exists(backup_path):
            logger.warning("备份文件不存在，跳过恢复: %s", backup_path)
            return None

        restore_filename = f"trade_engine_{restore_date.strftime('%Y%m%d')}_restored.db"
        restore_path = os.path.join(os.path.dirname(self.db_path), restore_filename)

        shutil.copy2(backup_path, restore_path)
        logger.info(
            "恢复备份: %s → %s（手动确认后覆盖 trade_engine.db）",
            backup_path,
            restore_path,
        )
        return restore_path

    # ----------------------------------------------------------
    # 列表
    # ----------------------------------------------------------

    def list_backups(self) -> list:
        """列出所有备份文件及其信息。"""
        pattern = os.path.join(self.backup_dir, "trade_engine_*.db")
        backups = []
        for filepath in sorted(glob.glob(pattern), reverse=True):
            basename = os.path.basename(filepath)
            mtime = os.path.getmtime(filepath)
            file_date = basename.replace("trade_engine_", "").replace(".db", "")
            size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 2)
            backups.append({
                "filename": basename,
                "date": file_date,
                "size_mb": size_mb,
                "mtime": datetime.fromtimestamp(mtime, tz=TZ_SHANGHAI).isoformat(),
            })
        return backups
