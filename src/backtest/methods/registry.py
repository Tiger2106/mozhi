"""
mozhi_platform.src.backtest.methods.registry — 方法/因子自动发现注册系统

功能（Phase 1 C模块）:
- C1: discover_methods() 自动发现方法目录
- C2: 精确匹配文件名→类名驼峰转换
- C3: @register_method 装饰器兜底（缩写命名兼容）
- C4: 多非私有子类确定性（优先精确匹配） + 导入异常保护
- C5: async on_bar 检测 & warning
- C6: requires_state=True 但 on_bar 未覆写告警
- C7: discover_factors() 因子发现
- C8: has_overridden_on_bar 检查（墨萱P1 on_bar告警）

作者: 墨衡
创建时间: 2026-05-17
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import re
import sys
import warnings
from typing import Any, Dict, List, Optional, Set, Tuple, Type

# ─── 模块级日志 ──────────────────────────────────────────────

logger = logging.getLogger(__name__)

# ─── 装饰器注册表 ────────────────────────────────────────────

_REGISTERED_METHODS: Dict[str, Type["BaseMethod"]] = {}
"""@register_method 装饰器注册表：{注册名: 方法类}"""

_REGISTERED_FACTORS: Dict[str, Type["BaseFactor"]] = {}
"""@register_factor 装饰器注册表：{注册名: 因子类}"""

# ──────────────────────────────────────────────────────────────────────
# C3: @register_method / @register_factor 装饰器
# ──────────────────────────────────────────────────────────────────────


def register_method(name: str) -> Any:
    """注册信号方法到自动发现系统中。

    用于文件名→类名无法精确匹配的场景（如截断缩写），
    装饰器兜底确保该方法能被 discover_methods() 发现。

    Args:
        name: 注册名（仅小写字母数字下划线）。

    Returns:
        装饰器函数。

    Examples:
        >>> @register_method("macd")
        ... class MACDMethod(BaseMethod):
        ...     ...
    """
    def decorator(cls: Type) -> Type:
        _REGISTERED_METHODS[name] = cls
        logger.debug("register_method: '%s' → %s", name, cls.__name__)
        return cls
    return decorator


def register_factor(name: str) -> Any:
    """注册因子到自动发现系统中。

    Args:
        name: 注册名。

    Returns:
        装饰器函数。
    """
    def decorator(cls: Type) -> Type:
        _REGISTERED_FACTORS[name] = cls
        logger.debug("register_factor: '%s' → %s", name, cls.__name__)
        return cls
    return decorator


# ──────────────────────────────────────────────────────────────────────
# C2: 文件名→类名转换
# ──────────────────────────────────────────────────────────────────────


def _filename_to_classname(filename: str) -> str:
    """将方法文件名转换为期望的类名。

    转换规则:
    1. 去除 `_method` / `_factor` 后缀及 `.py`
    2. 以下划线分割，各片段首字母大写拼接

    Args:
        filename: 如 "macd_method.py"、"rsi_factor.py"

    Returns:
        如 "MacdMethod"、"RsiFactor"

    Examples:
        >>> _filename_to_classname("macd_method.py")
        'MacdMethod'
        >>> _filename_to_classname("rsi_factor.py")
        'RsiFactor'
        >>> _filename_to_classname("simple_strategy.py")
        'SimpleStrategy'
    """
    stem = filename.replace(".py", "")
    # 去除后缀：如果以 _method 结尾则去掉 _method，其他保持
    for suffix in ("_method", "_factor", "_strategy"):
        if stem.endswith(suffix):
            stem = stem[:-len(suffix)]
            break
    # 驼峰化：下划线分割后首字母大写
    parts = stem.split("_")
    return "".join(p.capitalize() for p in parts if p)


def _find_method_class(
    module: Any,
    expected_cls_name: str,
    module_name: str,
    base_cls: Type,
) -> Optional[Type]:
    """在模块中查找方法类。

    查找顺序:
    1. 检查 @register_method 注册表
    2. 精确匹配 expected_cls_name
    3. 扫描所有 BaseMethod 子类，优先匹配精确类名

    Args:
        module: 已导入的模块
        expected_cls_name: 从文件名推导出的期望类名
        module_name: 模块名（用于日志）
        base_cls: 基类类型（BaseMethod 或 BaseFactor）

    Returns:
        Type or None: 找到的方法类
    """
    # ── C3: 注册表兜底 ──────────────────────────────────────
    # 从模块名（不含路径）中提取短名
    short_name = os.path.splitext(os.path.basename(module_name))[0]
    if base_cls.__name__ == "BaseMethod":
        method_registry = _REGISTERED_METHODS
    elif base_cls.__name__ == "BaseFactor":
        method_registry = _REGISTERED_FACTORS
    else:
        method_registry = {}

    if method_registry:
        for reg_name, reg_cls in method_registry.items():
            if reg_cls.__module__ == module.__name__:
                return reg_cls

    # ── C2: 优先精确匹配 ────────────────────────────────────
    if hasattr(module, expected_cls_name):
        candidate = getattr(module, expected_cls_name)
        if inspect.isclass(candidate) and issubclass(candidate, base_cls):
            return candidate

    # ── C4: 扫描多非私有子类 ────────────────────────────────
    candidates: List[Type] = []
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if name.startswith("_"):
            continue  # 跳过私有基类
        if issubclass(obj, base_cls) and obj is not base_cls:
            candidates.append(obj)

    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        # 精确匹配文件名对应的候选
        for c in candidates:
            if c.__name__ == expected_cls_name:
                return c
        # 仍无法确定，选择第一个
        logger.warning(
            "模块 %s 发现 %d 个 %s 子类，自动选择首个: %s",
            module_name, len(candidates), base_cls.__name__, candidates[0].__name__,
        )
        return candidates[0]

    return None  # 未找到


# ──────────────────────────────────────────────────────────────────────
# C5: async on_bar 检测
# ──────────────────────────────────────────────────────────────────────


def _check_async_on_bar(cls: Type) -> bool:
    """检测方法类是否将 on_bar 实现为 async def。

    Args:
        cls: 方法类。

    Returns:
        bool: 是 async 则返回 True 并抛 DeprecationWarning。
    """
    if not hasattr(cls, "on_bar"):
        return False
    on_bar = cls.on_bar
    if inspect.iscoroutinefunction(on_bar):
        warnings.warn(
            f"{cls.__name__}.on_bar() 声明为 async def，"
            f"回测引擎当前不支持异步钩子。该钩子将被忽略。",
            DeprecationWarning,
            stacklevel=3,
        )
        return True
    # 检查是否在子类中被覆写为 async
    for parent in cls.__mro__[1:]:
        if "on_bar" in parent.__dict__:
            break
    else:
        parent_on_bar = getattr(cls, "on_bar", None)
        if parent_on_bar and inspect.iscoroutinefunction(parent_on_bar):
            warnings.warn(
                f"{cls.__name__}.on_bar() 从父类继承 async 定义，"
                f"回测引擎当前不支持异步钩子。",
                DeprecationWarning,
                stacklevel=3,
            )
            return True
    return False


# ──────────────────────────────────────────────────────────────────────
# C6: has_overridden_on_bar 检查
# ──────────────────────────────────────────────────────────────────────


def has_overridden_on_bar(cls: Type) -> bool:
    """检查方法类是否在其自身而非基类中覆写了 on_bar。

    用于 Runner 中 requires_state=True 但 on_bar 未覆写时的告警。

    Args:
        cls: 方法类。

    Returns:
        bool: 在该类（或其任何非 object 中间父类）中覆写了 on_bar 则返回 True。
    """
    # 检查 cls 自身的 __dict__
    if "on_bar" in cls.__dict__:
        return True

    # 检查继承链上是否有覆写（排除 BaseMethod.object.on_bar 默认）
    for parent in cls.__mro__[1:]:
        if parent is object:
            break
        if "on_bar" in parent.__dict__:
            return True

    return False


# ──────────────────────────────────────────────────────────────────────
# C1: discover_methods() 主入口
# ──────────────────────────────────────────────────────────────────────


def discover_methods(
    methods_dir: Optional[str] = None,
    search_paths: Optional[List[str]] = None,
) -> Dict[str, Type["BaseMethod"]]:
    """自动发现并注册所有信号方法。

    遍历 methods_dir 或 search_paths 下所有以 ``_method.py`` 结尾的文件，
    动态导入并查找 BaseMethod 子类。

    Args:
        methods_dir: 方法目录路径（可选，默认自动检测）。
        search_paths: 额外的搜索路径列表（可选）。

    Returns:
        Dict[str, Type[BaseMethod]]: {方法名（小写蛇形）: 方法类}。

    Raises:
        FileNotFoundError: 如果指定目录不存在且无法自动推断。

    Examples:
        >>> methods = discover_methods()
        >>> "macd" in methods
        True
    """
    discovered: Dict[str, Type["BaseMethod"]] = {}

    # ── 确定搜索路径 ──────────────────────────────────────────
    dirs_to_scan: List[str] = []

    if methods_dir:
        dirs_to_scan.append(methods_dir)
    else:
        # 自动推断：使用 registry.py 所在目录
        registry_dir = os.path.dirname(os.path.abspath(__file__))
        dirs_to_scan.append(registry_dir)

    if search_paths:
        dirs_to_scan.extend(search_paths)

    # 将 dirs_to_scan 加入 sys.path 以便 importlib 能找到
    for d in dirs_to_scan:
        if d not in sys.path:
            sys.path.insert(0, d)

    # ── 遍历文件 ──────────────────────────────────────────────
    for scan_dir in dirs_to_scan:
        if not os.path.isdir(scan_dir):
            logger.warning("发现方法目录不存在: %s", scan_dir)
            continue

        for fname in sorted(os.listdir(scan_dir)):
            # C1: 过滤 _method.py 后缀
            if not fname.endswith("_method.py") and not fname.endswith(".py"):
                continue
            # 只加载 `*_method.py` 格式
            if not fname.endswith("_method.py"):
                continue

            filepath = os.path.join(scan_dir, fname)
            if not os.path.isfile(filepath):
                continue

            # C4: 跳过非标准命名
            if re.match(r"^\d", fname):
                logger.warning("跳过数字开头的文件名: %s", fname)
                continue

            # ── C4: 导入模块 ────────────────────────────────
            module_name = fname.replace(".py", "")
            try:
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                if spec is None or spec.loader is None:
                    logger.warning("无法加载模块 spec: %s", filepath)
                    continue

                module = importlib.util.module_from_spec(spec)
                # 缓存到 sys.modules 防止重复加载
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                logger.warning("导入方法模块失败 %s: %s", fname, e)
                continue

            # ── C2: 查找子类 ────────────────────────────────
            expected_cls = _filename_to_classname(fname) + "Method"
            # 检查带/不带 Method 后缀
            if hasattr(module, expected_cls):
                cls = getattr(module, expected_cls)
            else:
                expected_cls_no_method = _filename_to_classname(fname)
                cls = _find_method_class(
                    module, expected_cls_no_method, fname, _get_base_method()
                )

            if cls is None:
                logger.warning("模块 %s 中未发现 BaseMethod 子类", fname)
                continue

            # C5: async on_bar 检测
            _check_async_on_bar(cls)

            # ── 注册 ────────────────────────────────────────
            method_name = _cls_to_method_name(cls)
            discovered[method_name] = cls
            logger.info("发现方法: %s → %s", method_name, cls.__name__)

    return discovered


def _get_base_method():
    """懒加载 BaseMethod 以避免循环导入。"""
    from backtest.methods.base import BaseMethod
    return BaseMethod


def _get_base_factor():
    """懒加载 BaseFactor 以避免循环导入。"""
    from backtest.factors.base import BaseFactor
    return BaseFactor


def _cls_to_method_name(cls: Type) -> str:
    """将类名转换为小写蛇形方法名。

    Args:
        cls: 方法类。

    Returns:
        str: 小写蛇形方法名。
    """
    name = cls.__name__
    # 去除 "Method" 后缀
    if name.endswith("Method"):
        name = name[:-6]

    # MethodManifest 中优先使用 manifest name
    if hasattr(cls, "METHOD_META"):
        meta_name = cls.METHOD_META.get("name", "")
        if meta_name:
            return meta_name

    # 驼峰→蛇形
    s1 = re.sub(r"([A-Z])([A-Z][a-z])", r"\1_\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1)
    return s2.lower()


# ──────────────────────────────────────────────────────────────────────
# C7: discover_factors()
# ──────────────────────────────────────────────────────────────────────


def discover_factors(
    factors_dir: Optional[str] = None,
    search_paths: Optional[List[str]] = None,
) -> Dict[str, Type["BaseFactor"]]:
    """自动发现并注册所有因子。

    遍历 factors_dir 下所有以 ``_factor.py`` 结尾的文件，
    动态导入并查找 BaseFactor 子类，提取 FACTOR_META 元信息。

    Args:
        factors_dir: 因子目录路径（可选，默认自动检测）。
        search_paths: 额外的搜索路径列表（可选）。

    Returns:
        Dict[str, Type[BaseFactor]]: {因子名（小写蛇形）: 因子类}。

    Examples:
        >>> factors = discover_factors()
        >>> "momentum" in factors
        True
    """
    discovered: Dict[str, Type["BaseFactor"]] = {}

    dirs_to_scan: List[str] = []
    if factors_dir:
        dirs_to_scan.append(factors_dir)
    else:
        # 自动推断：使用 factors/ 目录
        registry_dir = os.path.dirname(os.path.abspath(__file__))
        factors_dir_auto = os.path.join(os.path.dirname(registry_dir), "factors")
        dirs_to_scan.append(factors_dir_auto)

    if search_paths:
        dirs_to_scan.extend(search_paths)

    for d in dirs_to_scan:
        if d not in sys.path:
            sys.path.insert(0, d)

    BaseFactor = _get_base_factor()

    for scan_dir in dirs_to_scan:
        if not os.path.isdir(scan_dir):
            logger.warning("发现因子目录不存在: %s", scan_dir)
            continue

        for fname in sorted(os.listdir(scan_dir)):
            if not fname.endswith("_factor.py"):
                continue

            filepath = os.path.join(scan_dir, fname)
            if not os.path.isfile(filepath):
                continue

            if re.match(r"^\d", fname):
                logger.warning("跳过数字开头的文件名: %s", fname)
                continue

            module_name = fname.replace(".py", "")
            try:
                spec = importlib.util.spec_from_file_location(module_name, filepath)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                logger.warning("导入因子模块失败 %s: %s", fname, e)
                continue

            expected_cls = _filename_to_classname(fname)
            cls = _find_method_class(module, expected_cls, fname, BaseFactor)

            if cls is None:
                logger.warning("模块 %s 中未发现 BaseFactor 子类", fname)
                continue

            # 提取因子名：优先 FACTOR_META.name
            meta = getattr(cls, "FACTOR_META", {})
            factor_name = meta.get("name", "") or _cls_to_method_name(cls)

            discovered[factor_name] = cls
            logger.info("发现因子: %s → %s", factor_name, cls.__name__)

    return discovered


# ──────────────────────────────────────────────────────────────────────
# C4 补充: 检查 requires_state 但 on_bar 未覆写
# ──────────────────────────────────────────────────────────────────────


def check_requires_state_on_bar(method_cls: Type) -> Optional[str]:
    """检查方法类声明 requires_state=True 但未覆写 on_bar。

    Args:
        method_cls: 方法类。

    Returns:
        Optional[str]: 告警消息文本，如无需告警则返回 None。
    """
    meta = getattr(method_cls, "METHOD_META", {})
    capabilities = meta.get("capabilities", {})
    requires_state = capabilities.get("requires_state", False)

    if requires_state and not has_overridden_on_bar(method_cls):
        msg = (
            f"{method_cls.__name__} 声明 capabilities.requires_state=True，"
            f"但未覆写 on_bar()。请注意：若不覆写 on_bar()，状态持久化将无效。"
        )
        return msg

    return None


# ─── 工具函数导出 ───────────────────────────────────────────

__all__ = [
    "discover_methods",
    "discover_factors",
    "register_method",
    "register_factor",
    "has_overridden_on_bar",
    "check_requires_state_on_bar",
    "filename_to_classname",
]

# 兼容导出别名
filename_to_classname = _filename_to_classname
