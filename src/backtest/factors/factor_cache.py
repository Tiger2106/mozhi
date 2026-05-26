"""
墨枢 - 因子数据缓存层（R1 阶段一：第2组-7）

按 key 缓存因子计算结果到 data/factors/cache/ 目录，
支持 TTL 过期，避免重复计算。
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

from pipeline_paths import factor_cache_dir

T = TypeVar("T")


def cached_factor_calc(
    key: str,
    calc_fn: Callable[..., T],
    *args: Any,
    ttl: int = 3600,
    force_refresh: bool = False,
    **kwargs: Any,
) -> T:
    """
    按 key 缓存因子计算结果。

    缓存位置：data/factors/cache/{key_hash}.pkl

    Parameters
    ----------
    key : str
        缓存键（建议包含因子名 + 标的 + 参数摘要）。
    calc_fn : Callable
        计算函数，在缓存未命中时调用。
    ttl : int
        缓存 TTL（秒，默认 3600 = 1h）。
    force_refresh : bool
        强制刷新缓存（忽略 TTL）。

    Returns
    -------
    T
        计算结果（与 calc_fn 返回值类型一致）。
    """
    cache_dir = factor_cache_dir()
    cache_key = _make_cache_key(key)
    cache_path = cache_dir / f"{cache_key}.pkl"
    meta_path = cache_dir / f"{cache_key}.meta.json"

    # ── 缓存命中检查 ─────────────────────────────
    if not force_refresh and cache_path.exists() and meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            cached_time = meta.get("cached_at", 0)
            if time.time() - cached_time < ttl:
                with open(cache_path, "rb") as f:
                    return pickle.load(f)
        except (json.JSONDecodeError, pickle.UnpicklingError, EOFError):
            pass  # 缓存损坏，重新计算

    # ── 缓存未命中／过期 → 计算 ─────────────────
    result = calc_fn(*args, **kwargs)

    # ── 写入缓存 ─────────────────────────────────
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(result, f)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "key": key,
                    "cached_at": time.time(),
                    "ttl": ttl,
                    "expires_at": time.time() + ttl,
                    "fn_name": getattr(calc_fn, "__name__", "unknown"),
                },
                f,
                ensure_ascii=False,
            )
    except (OSError, pickle.PicklingError) as e:
        # 缓存写入失败不应影响计算结果
        pass

    return result


def invalidate_cache(key_prefix: str) -> int:
    """
    使匹配 key_prefix 的缓存失效。

    Parameters
    ----------
    key_prefix : str
        key 前缀。例 "vwap_000300" 会使所有以该前缀开头的缓存失效。

    Returns
    -------
    int
        失效的缓存文件数。
    """
    cache_dir = factor_cache_dir()
    count = 0
    if not cache_dir.exists():
        return 0

    for f in cache_dir.iterdir():
        if f.suffix == ".meta.json":
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                if meta.get("key", "").startswith(key_prefix):
                    base = f.stem  # 去掉 .meta.json
                    pkl_path = cache_dir / f"{base}.pkl"
                    if pkl_path.exists():
                        pkl_path.unlink()
                    f.unlink()
                    count += 1
            except (json.JSONDecodeError, OSError):
                continue

    return count


def clear_all_cache() -> int:
    """
    清空所有因子缓存。

    Returns
    -------
    int
        删除的文件数。
    """
    cache_dir = factor_cache_dir()
    count = 0
    if not cache_dir.exists():
        return 0
    for f in cache_dir.iterdir():
        try:
            f.unlink()
            count += 1
        except OSError:
            continue
    return count


# ── 辅助 ────────────────────────────────────────────


def _make_cache_key(key: str) -> str:
    """生成定长、URL-safe 的缓存文件名。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def list_cache_stats() -> Dict[str, Any]:
    """
    查看缓存使用统计。

    Returns
    -------
    Dict[str, Any]
        {
            "total_files": int,
            "total_size_kb": float,
            "cached_keys": List[str],
            "oldest": float,
            "newest": float
        }
    """
    cache_dir = factor_cache_dir()
    if not cache_dir.exists():
        return {"total_files": 0, "cached_keys": [], "total_size_kb": 0.0}

    total_size = 0
    total_count = 0
    keys: list[str] = []
    times: list[float] = []

    for f in cache_dir.iterdir():
        if f.suffix == ".meta.json":
            total_count += 1
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    meta = json.load(fh)
                keys.append(meta.get("key", "?"))
                times.append(meta.get("cached_at", 0))
                pkl_path = f.with_suffix(".pkl")
                if pkl_path.exists():
                    total_size += pkl_path.stat().st_size
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "total_files": total_count,
        "total_size_kb": round(total_size / 1024, 2),
        "cached_keys": keys,
        "oldest": min(times) if times else 0,
        "newest": max(times) if times else 0,
    }
