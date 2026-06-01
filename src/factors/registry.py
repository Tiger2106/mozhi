"""
因子注册表 — FactorRegistry

支持按类别分类注册/查询因子，支持 batch_compute。

Author: 墨衡
Created: 2026-05-30T10:54:00+08:00
Version: v1
"""

from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)


class FactorRegistry:
    """因子注册表。

    管理所有因子实例，支持按类别分组注册和批量计算。

    用法：
        from src.factors.base import FactorBase
        from src.factors.registry import FactorRegistry

        registry = FactorRegistry()
        registry.register(momentum_5d, category='momentum')
        registry.register(momentum_20d, category='momentum')
        registry.register(reversal_1d, category='reversal')

        # 按类别获取
        momentum_factors = registry.get_by_category('momentum')

        # 批量计算
        results = registry.batch_compute('20260526')
    """

    def __init__(self):
        self._factors: dict[str, list[dict]] = {}  # category → [{name, instance}]
        self._all_factors: dict[str, object] = {}  # name → instance

    def register(
        self,
        factor: Any,
        category: str = 'default',
        name: Optional[str] = None,
    ) -> None:
        """注册一个因子实例。

        参数：
            factor: FactorBase 子类实例
            category: 类别标签（如 'momentum', 'reversal', 'quality' 等）
            name: 因子名称（默认使用 factor.name）
        """
        factor_name = name or getattr(factor, 'name', factor.__class__.__name__)

        if factor_name in self._all_factors:
            logger.warning("Factor '%s' already registered, overwriting", factor_name)

        self._all_factors[factor_name] = factor

        if category not in self._factors:
            self._factors[category] = []
        self._factors[category].append({'name': factor_name, 'instance': factor})

        logger.debug("Registered factor '%s' under category '%s'", factor_name, category)

    def get(self, name: str) -> Optional[Any]:
        """按名称获取因子实例。"""
        return self._all_factors.get(name)

    def get_all(self) -> list[dict]:
        """获取所有已注册的因子列表。

        返回：[{"name": ..., "instance": ..., "category": ...}, ...]
        """
        result = []
        for category, factors in self._factors.items():
            for f in factors:
                result.append({
                    'name': f['name'],
                    'instance': f['instance'],
                    'category': category,
                })
        return result

    def get_by_category(self, category: str) -> list[dict]:
        """按类别获取因子列表。"""
        return self._factors.get(category, [])

    def categories(self) -> list[str]:
        """获取所有已注册的类别名称。"""
        return list(self._factors.keys())

    def count(self) -> int:
        """获取已注册因子总数。"""
        return len(self._all_factors)

    def batch_compute(self, date: str) -> dict:
        """批量计算所有已注册的因子。

        参数：
            date: 截面日期 (YYYYMMDD)

        返回：
            dict: {
                "date": "20260526",
                "results": {
                    "momentum": {
                        "momentum_5d": [{"ts_code": "600000.SH", "value": ..., "mask": ...}, ...],
                        "momentum_20d": [...],
                    },
                    "reversal": { ... },
                    ...
                },
                "errors": {"factor_name": "error message", ...},
                "summary": {
                    "total_factors": 15,
                    "failed_factors": 0,
                    "completed": True,
                }
            }
        """
        results: dict[str, dict] = {}
        errors: dict[str, str] = {}

        for category, factors in self._factors.items():
            category_results = {}
            for f in factors:
                try:
                    category_results[f['name']] = f['instance'].compute(date)
                    logger.info("[batch] %s: %s computed successfully", category, f['name'])
                except Exception as e:
                    logger.error("[batch] %s: %s failed: %s", category, f['name'], e)
                    errors[f['name']] = str(e)
                    category_results[f['name']] = []
            results[category] = category_results

        return {
            'date': date,
            'results': results,
            'errors': errors,
            'summary': {
                'total_factors': self.count(),
                'failed_factors': len(errors),
                'completed': True,
            },
        }

    def __repr__(self) -> str:
        return (
            f"<FactorRegistry factors={self.count()} "
            f"categories={list(self._factors.keys())}>"
        )
