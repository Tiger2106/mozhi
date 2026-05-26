"""
test_method_manifest.py — validate_manifest / validate_factor_meta 单元测试

覆盖场景：
1. 完整格式全通过
2. 缺少必要顶层字段（name/version）
3. capabilities 缺少子字段
4. 非dict类型输入
5. validate_factor_meta
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backtest.methods.manifest import (
    validate_manifest,
    validate_factor_meta,
    MANIFEST_REQUIRED_FIELDS,
    CAPABILITIES_REQUIRED_FIELDS,
    FACTOR_META_REQUIRED_FIELDS,
)


def make_full_manifest(**overrides) -> dict:
    """生成完整合规的 MethodManifest 字典。"""
    manifest = {
        "name": "macd",
        "version": "1.0.0",
        "description": "MACD signal method",
        "capabilities": {
            "long_only": True,
            "intraday_support": False,
            "requires_state": True,
            "ai_generated": False,
            "risk_metrics": {},
        },
        "default_params": {"fast": 12, "slow": 26, "signal": 9},
        "tags": ["momentum"],
    }
    manifest.update(overrides)
    return manifest


class TestValidateManifest_完整格式全通过(unittest.TestCase):
    """场景1: 完整格式应返回空错误列表"""

    def test_full_manifest(self):
        """完整格式返回空列表"""
        manifest = make_full_manifest()
        errors = validate_manifest(manifest)
        self.assertEqual(errors, [])

    def test_minimal_manifest(self):
        """最少必要字段"""
        manifest = {
            "name": "rsi",
            "version": "1.0.0",
            "capabilities": {
                "long_only": True,
                "intraday_support": False,
                "requires_state": False,
            },
            "default_params": {"period": 14},
        }
        errors = validate_manifest(manifest)
        self.assertEqual(errors, [])

    def test_extended_capabilities(self):
        """带扩展能力的manifest"""
        manifest = {
            "name": "ml_signal",
            "version": "2.0.0",
            "capabilities": {
                "long_only": False,
                "intraday_support": True,
                "requires_state": True,
                "ai_generated": True,
                "risk_metrics": {"max_drawdown": 0.05},
            },
            "default_params": {"model": "xgboost"},
        }
        errors = validate_manifest(manifest)
        self.assertEqual(errors, [])


class TestValidateManifest_缺少顶层字段(unittest.TestCase):
    """场景2: 缺少必要顶层字段"""

    def test_missing_name(self):
        """缺少name应报错"""
        manifest = make_full_manifest(name="__missing__")
        del manifest["name"]
        errors = validate_manifest(manifest)
        self.assertIn("name", " ".join(errors))

    def test_missing_version(self):
        """缺少version应报错"""
        manifest = make_full_manifest(version="__missing__")
        del manifest["version"]
        errors = validate_manifest(manifest)
        self.assertIn("version", " ".join(errors))

    def test_missing_capabilities(self):
        """缺少capabilities应报错"""
        manifest = make_full_manifest(capabilities="__missing__")
        del manifest["capabilities"]
        errors = validate_manifest(manifest)
        self.assertIn("capabilities", " ".join(errors))

    def test_missing_default_params(self):
        """缺少default_params应报错"""
        manifest = make_full_manifest(default_params="__missing__")
        del manifest["default_params"]
        errors = validate_manifest(manifest)
        self.assertIn("default_params", " ".join(errors))

    def test_missing_multiple_fields(self):
        """同时缺少多个字段"""
        manifest = {
            "description": "no name or version",
            "capabilities": {
                "long_only": True,
                "intraday_support": False,
                "requires_state": False,
            },
            "default_params": {},
        }
        errors = validate_manifest(manifest)
        self.assertEqual(len(errors), 2)  # name + version
        error_text = " ".join(errors)
        self.assertIn("name", error_text)
        self.assertIn("version", error_text)


class TestValidateManifest_capabilities缺少字段(unittest.TestCase):
    """场景3: capabilities缺少子字段"""

    def test_missing_long_only(self):
        """capabilities缺少long_only"""
        manifest = make_full_manifest()
        del manifest["capabilities"]["long_only"]
        errors = validate_manifest(manifest)
        self.assertIn("long_only", " ".join(errors))

    def test_missing_all_subfields(self):
        """capabilities全部缺失"""
        manifest = make_full_manifest(capabilities={})
        errors = validate_manifest(manifest)
        self.assertEqual(len([e for e in errors if "capabilities" in e]), 3)

    def test_wrong_type_capability(self):
        """capabilities子字段类型错误"""
        manifest = make_full_manifest()
        manifest["capabilities"]["long_only"] = "yes"  # str instead of bool
        errors = validate_manifest(manifest)
        self.assertIn("bool", " ".join(errors))


class TestValidateManifest_非dict类型(unittest.TestCase):
    """场景4: 非dict类型输入"""

    def test_none_input(self):
        """None输入抛TypeError（not container）"""
        with self.assertRaises(TypeError):
            validate_manifest(None)

    def test_string_input(self):
        """字符串输入在get()时抛AttributeError"""
        with self.assertRaises(AttributeError):
            validate_manifest("not_a_dict")

    def test_list_input(self):
        """列表输入在get()时抛AttributeError"""
        with self.assertRaises(AttributeError):
            validate_manifest(["name", "version"])


class TestValidateFactorMeta(unittest.TestCase):
    """场景5: validate_factor_meta"""

    def test_full_factor_meta(self):
        """完整因子元信息"""
        meta = {
            "name": "momentum",
            "version": "1.0.0",
            "category": "momentum",
            "default_params": {"window": 20},
        }
        errors = validate_factor_meta(meta)
        self.assertEqual(errors, [])

    def test_missing_name(self):
        """缺失name"""
        meta = {
            "version": "1.0.0",
            "category": "momentum",
            "default_params": {"window": 20},
        }
        errors = validate_factor_meta(meta)
        self.assertIn("name", " ".join(errors))

    def test_missing_version(self):
        """缺失version"""
        meta = {
            "name": "momentum",
            "category": "momentum",
            "default_params": {"window": 20},
        }
        errors = validate_factor_meta(meta)
        self.assertIn("version", " ".join(errors))

    def test_missing_category(self):
        """缺失category"""
        meta = {
            "name": "momentum",
            "version": "1.0.0",
            "default_params": {"window": 20},
        }
        errors = validate_factor_meta(meta)
        self.assertIn("category", " ".join(errors))

    def test_missing_all(self):
        """全缺失"""
        errors = validate_factor_meta({})
        self.assertEqual(len(errors), 4)

    def test_extra_fields(self):
        """额外字段不影响校验"""
        meta = {
            "name": "volatility",
            "version": "1.0.0",
            "category": "risk",
            "default_params": {},
            "description": "Extra field is fine",
            "author": "test",
        }
        errors = validate_factor_meta(meta)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
