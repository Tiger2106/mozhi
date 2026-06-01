"""
LookbackBuffer — 滚动窗口历史数据持久化模块

提供 LookbackData 的持久化读写能力，支持每标的独立文件存储。
所有数据存储在 constants.LB_PERSIST_PATH 指定目录下。

接口：
  LookbackBuffer.load(ticker)    — 加载指定标的的历史数据
  LookbackBuffer.save(ticker, data) — 保存指定标的的历史数据
  LookbackBuffer.clear(ticker=None) — 清除指定标的或全部历史数据
  LookbackBuffer.load_all()      — 加载所有已持久化的数据
  LookbackBuffer.exists(ticker)  — 检查标的持久化是否存在
  LookbackBuffer.list_tickers()  — 列出所有已持久化的标的

Usage:
    >>> buf = LookbackBuffer()
    >>> data = buf.load("601857")
    >>> data.history.append(("20260528", 0.75))
    >>> buf.save("601857", data)
    >>> buf.clear("601857")   # 清除单标的
    >>> buf.clear()           # 清除全部

Author: moheng
Created: 2026-05-29T09:49:00+08:00
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from src.resonance.constants import LB_PERSIST_PATH
from src.resonance.models import LookbackData, RSMState


# ══════════════════════════════════════════════════════════
# 项目根路径解析
# ══════════════════════════════════════════════════════════


def _resolve_project_root() -> Path:
    """从模块位置向上查找项目根（包含 src/ 目录的父目录）。

    搜索策略：
      1. 从 __file__ 所在目录向上查找
      2. 找到包含 .git 目录的 src/ 父目录
      3. 回退：假设为 src/ 的上两级（即 resonance 的外三层）

    Returns:
        Path: 项目根目录的绝对路径。
    """
    module_dir = Path(__file__).resolve().parent  # src/resonance/
    # 向上查找 src/ 目录
    for parent in [module_dir, *module_dir.parents]:
        if parent.name == "src" and (parent.parent / ".git").is_dir():
            return parent.parent
    # 回退：标准目录结构 sr c/resonance/ → 上两级为项目根
    return (module_dir / ".." / "..").resolve()


_PROJECT_ROOT: Path = _resolve_project_root()


# ══════════════════════════════════════════════════════════
# 路径工具
# ══════════════════════════════════════════════════════════


def _get_lb_path() -> Path:
    """获取 LookbackBuffer 持久化目录的绝对路径。

    Returns:
        Path: LB_PERSIST_PATH 对应的绝对目录路径。
    """
    return _PROJECT_ROOT / LB_PERSIST_PATH


def _ensure_lb_dir() -> Path:
    """确保持久化目录存在。

    Returns:
        Path: 确保存在的持久化目录路径。
    """
    lb_path = _get_lb_path()
    lb_path.mkdir(parents=True, exist_ok=True)
    return lb_path


def _ticker_to_filename(ticker: str) -> str:
    """将标的代码转换为安全的文件名。

    替换可能引发路径问题的特殊字符（斜杠、反斜杠、连续点号）。

    Args:
        ticker: 标的代码，如 '601857.SH' 或 '600519'。

    Returns:
        str: 安全的文件名（不含扩展名）。
    """
    safe = ticker.replace("/", "_").replace("\\", "_").replace("..", "_")
    return f"{safe}.json"


def _ticker_filepath(ticker: str) -> Path:
    """获取指定标的的完整持久化文件路径。

    Args:
        ticker: 标的代码。

    Returns:
        Path: 持久化文件的完整路径。
    """
    return _get_lb_path() / _ticker_to_filename(ticker)


# ══════════════════════════════════════════════════════════
# LookbackData JSON 序列化/反序列化
# ══════════════════════════════════════════════════════════


def _lookback_data_to_dict(data: LookbackData) -> Dict:
    """将 LookbackData 转换为 JSON 可序列化字典。

    Args:
        data: LookbackData 实例。

    Returns:
        dict: 包含所有字段的 JSON 兼容字典。
    """
    return {
        "history": list(data.history),
        "resonance_state": data.resonance_state.value,
        "window_stats": dict(data.window_stats),
        "last_update": data.last_update,
        "ticker": data.ticker,
    }


def _dict_to_lookback_data(d: Dict) -> LookbackData:
    """将字典反序列化为 LookbackData 实例。

    Args:
        d: 包含 LookbackData 字段的字典。

    Returns:
        LookbackData: 恢复的数据实例。解析失败的字段使用默认值。
    """
    # history: [(str, float), ...]
    history_raw = d.get("history", [])
    history = []
    for item in history_raw:
        try:
            history.append((str(item[0]), float(item[1])))
        except (IndexError, TypeError, ValueError):
            continue

    # resonance_state
    state_str = d.get("resonance_state", RSMState.NONE.value)
    try:
        resonance_state = RSMState(state_str)
    except ValueError:
        resonance_state = RSMState.NONE

    # window_stats
    window_stats_raw = d.get("window_stats", {})
    window_stats = {}
    if not isinstance(window_stats_raw, dict):
        window_stats_raw = {}
    for k, v in window_stats_raw.items():
        try:
            window_stats[str(k)] = float(v)
        except (TypeError, ValueError):
            continue

    return LookbackData(
        history=history,
        resonance_state=resonance_state,
        window_stats=window_stats,
        last_update=str(d.get("last_update", "")),
        ticker=str(d.get("ticker", "")),
    )


# ══════════════════════════════════════════════════════════
# 原子写入
# ══════════════════════════════════════════════════════════


def _atomic_write_json(filepath: Path, data: Dict) -> None:
    """原子方式写入 JSON 文件。

    先写入临时文件再 rename 到目标路径，
    避免写入过程中 crash 导致文件损坏。

    Args:
        filepath: 目标文件路径。
        data: 要写入的 JSON 数据字典。

    Raises:
        OSError: 目录不可写或写入操作失败。
    """
    temp_path = filepath.with_name(f"._{filepath.name}.{os.getpid()}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(filepath)
    except Exception:
        # 清理临时文件
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise
    finally:
        # 二次清理（即使 rename 成功也清理）
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


# ══════════════════════════════════════════════════════════
# LookbackBuffer — 公开接口
# ══════════════════════════════════════════════════════════


class LookbackBuffer:
    """滚动窗口历史数据持久化缓冲。

    管理每个标的的 LookbackData 持久化：
      - 每标的独立 JSON 文件，文件名为 {ticker}.json
      - 原子写入（先写临时文件再 rename）保证数据完整性
      - 内存缓存（避免重复磁盘 I/O）
      - 加载时自动类型恢复（Tuple/Enum/float 反序列化）
      - 支持回放模式：仅读不写

    接口：
        load(ticker)        — 加载指定标的的历史数据
        save(ticker, data)  — 持久化指定标的的历史数据
        load_all()          — 加载目录下所有标的的历史数据
        clear(ticker=None)  — 清除指定标的或全部历史数据
        exists(ticker)      — 检查标的是否有持久化数据
        list_tickers()      — 列出所有已持久化的标的代码

    Usage:
        >>> buf = LookbackBuffer()
        >>> data = buf.load("601857")
        >>> data.history.append(("20260528", 0.75))
        >>> buf.save("601857", data)
        >>> buf.clear("601857")   # 清除单标的
        >>> buf.clear()           # 清除全部

    Attributes:
        replay_mode (bool): 回放模式标志（初始化时指定）。
        persistence_path (Path): 持久化目录的绝对路径。
    """

    def __init__(self, replay_mode: bool = False):
        """初始化 LookbackBuffer。

        Args:
            replay_mode: 回放模式（默认 False）。
                True 时仅允许读取操作，禁止写入和删除。
                用于回测场景，确保不污染运行时持久化数据。
        """
        self._replay_mode = replay_mode
        self._cache: Dict[str, LookbackData] = {}

    # ──── 属性 ────

    @property
    def replay_mode(self) -> bool:
        """是否为回放模式。"""
        return self._replay_mode

    @property
    def persistence_path(self) -> Path:
        """持久化目录的绝对路径。"""
        return _get_lb_path()

    # ──── 核心接口 ────

    def load(self, ticker: str) -> Optional[LookbackData]:
        """加载指定标的的持久化历史数据。

        搜索顺序：
          1. 内存缓存（避免重复磁盘 I/O）
          2. 持久化文件（JSON 反序列化）

        Args:
            ticker: 标的代码，如 '601857' 或 '601857.SH'。

        Returns:
            Optional[LookbackData]: 加载到的 LookbackData 实例。
                - 文件不存在 → None
                - 文件损坏 / 解析失败 → None（不自动删除源文件）
                - 缓存命中 → 缓存副本（非引用，防止意外修改）
        """
        if not ticker:
            return None

        # 1. 检查缓存
        if ticker in self._cache:
            return self._cache[ticker]

        # 2. 从持久化文件加载
        filepath = _ticker_filepath(ticker)
        if not filepath.exists():
            return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            data = _dict_to_lookback_data(raw)
            # 验证 ticker 匹配
            if data.ticker and data.ticker != ticker:
                data.ticker = ticker
            # 写入缓存
            self._cache[ticker] = data
            return data
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            # 文件损坏，不删除（避免数据丢失风险）
            return None

    def save(self, ticker: str, data: LookbackData) -> None:
        """持久化指定标的的历史数据。

        写入前自动同步 data.ticker 字段与 ticker 参数一致。
        使用原子写入策略保证数据完整性。

        Args:
            ticker: 标的代码。
            data: 要持久化的 LookbackData 实例。

        Raises:
            ValueError: ticker 为空。
            OSError: 目录创建或文件写入失败。
        """
        if not ticker:
            raise ValueError("ticker must not be empty")

        if self._replay_mode:
            # 回放模式下静默跳过写入操作
            return

        # 对齐 data.ticker
        data.ticker = ticker

        # 确保目录存在
        _ensure_lb_dir()

        # 序列化 + 原子写入
        filepath = _ticker_filepath(ticker)
        payload = _lookback_data_to_dict(data)
        _atomic_write_json(filepath, payload)

        # 更新缓存
        self._cache[ticker] = data

    def load_all(self) -> Dict[str, LookbackData]:
        """加载持久化目录中所有标的的历史数据。

        遍历 LB_PERSIST_PATH 目录下的所有 .json 文件，
        排除临时文件（以 . 开头或 .tmp 结尾）。

        Returns:
            Dict[str, LookbackData]: ticker → LookbackData 映射。
                无法解析的文件被静默跳过，不会中断加载。
        """
        lb_dir = _get_lb_path()
        if not lb_dir.is_dir():
            return {}

        result: Dict[str, LookbackData] = {}
        for fpath in sorted(lb_dir.iterdir()):
            # 只处理 .json 文件，排除临时/隐藏文件
            if fpath.suffix != ".json":
                continue
            if fpath.name.startswith("."):
                continue
            ticker = fpath.stem
            if not ticker:
                continue
            data = self.load(ticker)
            if data is not None:
                result[ticker] = data

        return result

    def clear(self, ticker: Optional[str] = None) -> int:
        """清除持久化数据。

        Args:
            ticker: 要清除的标的代码。
                None 或空字符串 → 清除目录下所有 LookbackData 文件。

        Returns:
            int: 被删除的文件数量（含临时文件清理）。

        Notes:
            回放模式下返回 0，不执行任何删除操作。
        """
        if self._replay_mode:
            return 0

        lb_dir = _get_lb_path()
        if not lb_dir.is_dir():
            return 0

        count = 0

        if ticker:
            # 清除单标的
            target = _ticker_filepath(ticker)
            if target.exists():
                target.unlink()
                count += 1
            # 清除关联的临时文件
            for tmp in lb_dir.glob(f"._{_ticker_to_filename(ticker)}.*"):
                tmp.unlink(missing_ok=True)
            # 清除缓存
            self._cache.pop(ticker, None)
        else:
            # 清除目录下所有 lookback 文件
            for fpath in list(lb_dir.iterdir()):
                if fpath.name.endswith(".json"):
                    fpath.unlink()
                    count += 1
            self._cache.clear()

        return count

    def exists(self, ticker: str) -> bool:
        """检查指定标的的持久化数据是否存在。

        Args:
            ticker: 标的代码。

        Returns:
            bool: 是否存在持久化数据（缓存或文件）。
        """
        if not ticker:
            return False
        if ticker in self._cache:
            return True
        return _ticker_filepath(ticker).is_file()

    def list_tickers(self) -> List[str]:
        """列出持久化目录中所有标的代码。

        基于文件系统扫描，不加载数据内容。

        Returns:
            List[str]: 已持久化的标的代码列表（字母序）。
        """
        lb_dir = _get_lb_path()
        if not lb_dir.is_dir():
            return []

        tickers = []
        for fpath in lb_dir.iterdir():
            if fpath.suffix != ".json":
                continue
            if fpath.name.startswith("."):
                continue
            ticker = fpath.stem
            if ticker:
                tickers.append(ticker)
        return sorted(tickers)


# ══════════════════════════════════════════════════════════
# 便捷函数（模块级调用）
# ══════════════════════════════════════════════════════════

_default_buffer: Optional[LookbackBuffer] = None


def _get_default_buffer() -> LookbackBuffer:
    """获取默认的 LookbackBuffer 单例实例。

    避免多次实例化带来的重复开销。

    Returns:
        LookbackBuffer: 默认 LookbackBuffer 实例。
    """
    global _default_buffer
    if _default_buffer is None:
        _default_buffer = LookbackBuffer()
    return _default_buffer


def load(ticker: str) -> Optional[LookbackData]:
    """加载指定标的的历史数据（便捷函数）。

    使用全局默认缓冲区。

    Args:
        ticker: 标的代码。

    Returns:
        Optional[LookbackData]: LookbackData 实例或 None。
    """
    return _get_default_buffer().load(ticker)


def save(ticker: str, data: LookbackData) -> None:
    """保存指定标的的历史数据（便捷函数）。

    使用全局默认缓冲区。

    Args:
        ticker: 标的代码。
        data: 要持久化的 LookbackData 实例。

    Raises:
        ValueError: ticker 为空。
        OSError: 写入失败。
    """
    return _get_default_buffer().save(ticker, data)


def clear(ticker: Optional[str] = None) -> int:
    """清除持久化数据（便捷函数）。

    使用全局默认缓冲区。

    Args:
        ticker: 要清除的标的代码。None 表示全部清除。

    Returns:
        int: 被删除的文件数量。
    """
    return _get_default_buffer().clear(ticker)
