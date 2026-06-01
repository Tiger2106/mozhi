"""
轻量内存 Profiler — MemorySnapshot

记录进程中各标记点的进程RSS、系统可用/总内存，
最终输出 Start/Peak/End/Delta 汇总表格。

Usage:
    profiler = MemorySnapshot()
    profiler.take('start')
    ...
    profiler.take('batch_10')
    ...
    profiler.take('end')
    print(profiler.report())

Author: 墨衡
Created: 2026-05-30T21:21:00+08:00
"""

import gc
import os
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class SnapshotPoint:
    """单个快照点数据"""
    tag: str
    timestamp: float  # Unix timestamp
    rss_mb: float     # 进程 RSS (MB)
    sys_avail_gb: float  # 系统可用内存 (GB)
    sys_total_gb: float  # 系统总内存 (GB)


def _mb_to_gb(mb: float) -> float:
    return round(mb / 1024.0, 2)


class MemorySnapshot:
    """轻量内存快照 Profiler。

    按 tag 记录关键节点的内存状态，最后输出汇总报告。
    支持在没有 psutil 的环境降级运行（记录标记但值为 -1）。
    """

    def __init__(self):
        self._pid = os.getpid()
        self._points: List[SnapshotPoint] = []
        self._psutil_available: bool = False

        try:
            import psutil
            self._psutil = psutil
            self._psutil_available = True
            self._process = psutil.Process(self._pid)
        except ImportError:
            self._psutil_available = False
            import logging
            logging.getLogger(__name__).warning(
                "[MemorySnapshot] psutil not installed, snapshots will record -1"
            )

    @property
    def pid(self) -> int:
        return self._pid

    @property
    def count(self) -> int:
        return len(self._points)

    def take(self, tag: str) -> "MemorySnapshot":
        """记录当前内存快照。

        Parameters
        ----------
        tag : str
            标记名称（如 'start', 'batch_10', 'end'）

        Returns
        -------
        MemorySnapshot
            self — 支持链式调用
        """
        ts = time.time()
        rss_mb = -1.0
        sys_avail_gb = -1.0
        sys_total_gb = -1.0

        if self._psutil_available:
            try:
                rss_bytes = self._process.memory_info().rss
                rss_mb = round(rss_bytes / (1024.0 * 1024.0), 2)
            except Exception:
                rss_mb = -1.0

            try:
                vmem = self._psutil.virtual_memory()
                sys_avail_gb = round(vmem.available / (1024.0 ** 3), 2)
                sys_total_gb = round(vmem.total / (1024.0 ** 3), 2)
            except Exception:
                sys_avail_gb = -1.0
                sys_total_gb = -1.0

        self._points.append(SnapshotPoint(
            tag=tag,
            timestamp=ts,
            rss_mb=rss_mb,
            sys_avail_gb=sys_avail_gb,
            sys_total_gb=sys_total_gb,
        ))
        return self

    def report(self) -> str:
        """输出 Start / Peak / End / Delta 汇总表格。

        Returns
        -------
        str
            格式化的汇总表格字符串
        """
        if not self._points:
            return "[MemorySnapshot] No snapshots recorded."

        # 按 tag 查找关键点
        def _find(tag_prefix: str) -> Optional[SnapshotPoint]:
            for p in self._points:
                if p.tag == tag_prefix or p.tag.startswith(tag_prefix):
                    return p
            return None

        start = _find("start")
        end = _find("end")
        # Peak: 进程 RSS 最大的点
        peak = max(self._points, key=lambda p: p.rss_mb) if self._points else None

        # Delta: end - start
        delta_rss = -1.0
        delta_avail = -1.0
        if start and end and start.rss_mb >= 0 and end.rss_mb >= 0:
            delta_rss = round(end.rss_mb - start.rss_mb, 2)
        if start and end and start.sys_avail_gb >= 0 and end.sys_avail_gb >= 0:
            delta_avail = round(end.sys_avail_gb - start.sys_avail_gb, 2)

        # 格式化时间
        def _ts(pt: SnapshotPoint) -> str:
            return time.strftime("%H:%M:%S", time.localtime(pt.timestamp))

        lines: List[str] = []
        lines.append("=" * 80)
        lines.append("  MemorySnapshot Report (PID=%d)" % self._pid)
        lines.append("=" * 80)
        lines.append(f"  {'Metric':<25} {'Start':>15} {'Peak':>15} {'End':>15} {'Delta':>15}")
        lines.append("  " + "-" * 25 + " " + "-" * 15 + " " + "-" * 15 + " " + "-" * 15 + " " + "-" * 15)
        lines.append(f"  {'Process RSS (MB)':<25} {start.rss_mb if start else 'N/A':>15} {peak.rss_mb if peak else 'N/A':>15} {end.rss_mb if end else 'N/A':>15} {delta_rss if delta_rss >= 0 else 'N/A':>15}")
        lines.append(f"  {'Sys Available (GB)':<25} {start.sys_avail_gb if start else 'N/A':>15} {peak.sys_avail_gb if peak else 'N/A':>15} {end.sys_avail_gb if end else 'N/A':>15} {delta_avail if delta_avail >= 0 else 'N/A':>15}")
        lines.append(f"  {'Sys Total (GB)':<25} {start.sys_total_gb if start else 'N/A':>15} {peak.sys_total_gb if peak else 'N/A':>15} {end.sys_total_gb if end else 'N/A':>15} {'N/A':>15}")
        lines.append("")
        lines.append(f"  {'Tag':<25} {'Time':>15} {'RSS(MB)':>15} {'Avail(GB)':>15} {'Total(GB)':>15}")
        lines.append("  " + "-" * 25 + " " + "-" * 15 + " " + "-" * 15 + " " + "-" * 15 + " " + "-" * 15)
        for p in self._points:
            lines.append(f"  {p.tag:<25} {_ts(p):>15} {p.rss_mb if p.rss_mb >= 0 else 'N/A':>15} {p.sys_avail_gb if p.sys_avail_gb >= 0 else 'N/A':>15} {p.sys_total_gb if p.sys_total_gb >= 0 else 'N/A':>15}")
        lines.append("=" * 80)
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<MemorySnapshot pid={self._pid} "
            f"points={len(self._points)} "
            f"psutil={'yes' if self._psutil_available else 'no'}>"
        )

# ---------------------------------------------------------------------------
# MemoryMonitor — 运行时自适应内存监控 (Author: Moheng, 2026-05-31)
# ---------------------------------------------------------------------------

# 四色水位阈值（GB）
THRESHOLD_CRIT = 1.0    # <1.0 GB → 终止
THRESHOLD_RED = 1.5     # 1.0~1.5 GB → 降级
THRESHOLD_YELLOW = 2.0  # 1.5~2.0 GB → 告警
# >2.0 GB → GREEN（正常）


class MemoryMonitor:
    """运行时自适应内存监控器。

    提供四色水位检测和后台守护线程（1次/秒），
    供管线在 run_batch_streaming 中实时降级决策。

    Thresholds
    ----------
    GREEN  : >2.0 GB 可用 — 正常运行
    YELLOW : 1.5~2.0 GB — 告警（仅日志）
    RED    : 1.0~1.5 GB — 降级（step 1W->2W + gc.collect x2）
    CRIT   : <1.0 GB — 终止（抛 RuntimeError）

    Usage
    -----
    >>> monitor = MemoryMonitor()
    >>> level = monitor.check_once()   # 同步模式
    >>> monitor.start()                 # 启动后台线程
    >>> # ... 运行中 ...
    >>> monitor.stop()                  # 停止
    """

    LEVELS = ("GREEN", "YELLOW", "RED", "CRIT", "UNKNOWN")

    def __init__(self):
        self._lock = threading.Lock()
        self._current_level = "UNKNOWN"
        self._thread = None
        self._stop_event = threading.Event()
        self._psutil_available = True

        try:
            import psutil
            self._psutil = psutil
        except ImportError:
            self._psutil_available = False
            import logging
            logging.getLogger(__name__).warning(
                "[MemoryMonitor] psutil not installed; check_once() returns UNKNOWN"
            )

    @property
    def current_level(self):
        with self._lock:
            return self._current_level

    @staticmethod
    def _classify(available_gb):
        if available_gb < 0:
            return "UNKNOWN"
        if available_gb < THRESHOLD_CRIT:
            return "CRIT"
        if available_gb < THRESHOLD_RED:
            return "RED"
        if available_gb < THRESHOLD_YELLOW:
            return "YELLOW"
        return "GREEN"

    def check_once(self):
        """同步模式：检测一次可用内存，返回水位等级。"""
        if not self._psutil_available:
            return "UNKNOWN"
        try:
            vmem = self._psutil.virtual_memory()
            available_gb = vmem.available / (1024.0 ** 3)
            level = self._classify(available_gb)
            with self._lock:
                self._current_level = level
            return level
        except Exception:
            import logging
            logging.getLogger(__name__).exception("[MemoryMonitor] check_once failed")
            return "UNKNOWN"

    def _loop(self):
        while not self._stop_event.is_set():
            self.check_once()
            self._stop_event.wait(timeout=1.0)

    def start(self):
        """启动后台守护线程。psutil不可用时仅警告，不抛异常。"""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
        if not self._psutil_available:
            return
        self._stop_event.clear()
        t = threading.Thread(
            target=self._loop,
            name="MemoryMonitor-daemon",
            daemon=True,
        )
        t.start()
        with self._lock:
            self._thread = t

    def stop(self, timeout=2.0):
        with self._lock:
            if not self._thread:
                return
            t = self._thread
            self._stop_event.set()
        t.join(timeout=timeout)
        if t.is_alive():
            import logging
            logging.getLogger(__name__).warning(
                "[MemoryMonitor] daemon thread did not stop within %.1fs", timeout
            )
        with self._lock:
            self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


# ---------------------------------------------------------------------------
# 预设降级回调 (Author: Moheng, 2026-05-31)
# ---------------------------------------------------------------------------

DEFAULT_DEGRADE = {
    "step_remap": {"1W": "2W", "2W": "1M", "1M": "1M", "1D": "1W"},
}


def default_degrade_callback(level, config):
    """预设降级回调函数。

    - YELLOW : 仅日志警告
    - RED    : step降级 + gc.collect() x2
    - CRIT   : 抛 RuntimeError
    """
    import logging
    logger = logging.getLogger(__name__)

    if level == "YELLOW":
        logger.warning("[Degrade] YELLOW: available memory 1.5~2.0 GB - monitoring")

    elif level == "RED":
        current_step = config.get("pipeline.step", "1W")
        new_step = DEFAULT_DEGRADE["step_remap"].get(current_step, "2W")
        config["pipeline.step"] = new_step
        gc.collect()
        gc.collect()
        logger.warning("[Degrade] RED: degraded step %s -> %s, gc.collect() x2",
                        current_step, new_step)

    elif level == "CRIT":
        logger.critical("[Degrade] CRIT: available memory < 1.0 GB - aborting")
        raise RuntimeError("CRITICAL: available memory < 1GB")


# ---------------------------------------------------------------------------
# 预算估算 (Author: Moheng, 2026-05-31)
# ---------------------------------------------------------------------------


def estimate_safe_step(
    available_gb: float,
    n_factors: int = 15,
    n_stocks: int = 50,
    current_step: str = "1W",
    reserve_gb: float = 0.5,
) -> str:
    """根据可用内存估算安全的截面步长。

    Parameters
    ----------
    available_gb : float
        当前系统可用内存（GB）
    n_factors : int
        因子数量（默认 15）
    n_stocks : int
        股票数量（默认 50）
    current_step : str
        当前步长（占位，保留兼容）
    reserve_gb : float
        预留内存安全边际（默认 0.5 GB）

    Returns
    -------
    str
        推荐的步长：1W / 2W / 1M，或 0（无可执行预算时）
    """
    per_section_gb = (n_factors * n_stocks * 0.00004) + 0.05
    usable_gb = max(0, available_gb - reserve_gb)

    if usable_gb <= 0 or per_section_gb <= 0:
        return "0"

    safe_sections = usable_gb / per_section_gb

    if safe_sections >= 50:
        return "1W"
    elif safe_sections >= 10:
        return "2W"
    elif safe_sections >= 2:
        return "1M"
    else:
        return "0"


def estimate_safe_batch_size(
    available_gb: float,
    n_factors: int = 15,
    n_stocks: int = 50,
    reserve_gb: float = 0.5,
) -> int:
    """根据可用内存估算安全的截面批处理数。
    
    Returns
    -------
    int
        安全的截面处理数量。0 表示无可执行预算。
    """
    per_section_gb = (n_factors * n_stocks * 0.00004) + 0.05
    usable_gb = max(0, available_gb - reserve_gb)

    if usable_gb <= 0 or per_section_gb <= 0:
        return 0

    return max(0, int(usable_gb / per_section_gb))
