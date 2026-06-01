#!/usr/bin/env python3
"""
文件路径合规检查器

检查文件路径是否位于正确的基目录(mozhi_platform/), 
自动识别并报告误写入 mo_zhi_sharereports/ 或其他非合规目录的路径。

白名单例外：
  - signals/ 目录下的信号文件
  - .done / .failed 信号文件

Author: 墨衡 (moheng)
Created: 2026-06-01
"""

import os
import re
import sys

# ── 常量 ──────────────────────────────────────────────
CORRECT_BASE = "mozhi_platform"
WRONG_BASE = "mo_zhi_sharereports"

# 实际错误的 base 名称（用户实际会写错的目录名）
WRONG_BASE_PATTERNS = [
    "mo_zhi_sharereports",
    "mozhi_sharereports",
]

WHITELIST_DIRS = [
    "signals",         # signals/ 下的信号文件
]

WHITELIST_EXTENSIONS = [
    ".done",
    ".failed",
]

# ── 核心函数 ──────────────────────────────────────────


def _normalize(p: str) -> str:
    """统一路径分隔符为反斜杠"""
    return p.replace("/", "\\")


def _extract_stem(p: str) -> str:
    """提取文件名（不含扩展名，大写）"""
    name = os.path.basename(p)
    name = os.path.splitext(name)[0]
    return name.upper()


def _is_whitelisted(p: str) -> bool:
    """检查路径是否属于白名单例外"""
    normalized = _normalize(p)

    # 白名单目录：signals/ 下的文件
    for wd in WHITELIST_DIRS:
        if f"{wd}\\" in normalized or normalized.startswith(f"{wd}\\"):
            return True

    # 白名单扩展名：.done / .failed
    for ext in WHITELIST_EXTENSIONS:
        if normalized.endswith(ext):
            return True

    return False


def _contains_wrong_base(p: str) -> tuple:
    """
    检查路径是否包含错误的基目录。

    Returns:
        (found: bool, matched_str: str)  —  matched_str 为匹配到的错误基目录名
    """
    normalized = _normalize(p)
    for wb in WRONG_BASE_PATTERNS:
        if f"{wb}\\" in normalized or normalized.startswith(f"{wb}\\"):
            return True, wb
    return False, ""


def _contains_correct_base(p: str) -> bool:
    """检查路径是否包含正确的基目录"""
    normalized = _normalize(p)
    cb = f"{CORRECT_BASE}\\"
    return cb in normalized or normalized.startswith(f"{cb}")


def check_paths(paths: list) -> list:
    """
    检查文件路径列表是否符合路径合规要求。

    Args:
        paths: 文件路径列表（支持完整路径或相对路径）

    Returns:
        违规说明列表；空列表表示全部合规
    """
    violations = []
    cwd = os.getcwd()

    for p in paths:
        # 将相对路径解析为绝对路径再检查
        if not os.path.isabs(p):
            p = os.path.normpath(os.path.join(cwd, p))
        normalized = _normalize(p)
        stem = _extract_stem(p)

        # 1. 已包含正确基目录 → 通过
        if _contains_correct_base(normalized):
            continue

        # 2. 白名单例外 → 通过（即使路径在 mo_zhi_sharereports 下）
        if _is_whitelisted(normalized):
            continue

        # 3. 检查是否在错误基目录下
        found_wrong, wrong_match = _contains_wrong_base(normalized)
        if found_wrong:
            violations.append(
                f"{stem}: 应位于 {CORRECT_BASE}/src/ 而非 {wrong_match}/src/"
            )
            continue

        # 4. 未包含正确基目录 → 报告路径前缀错误
        violations.append(
            f"{stem}: 路径前缀错误 — 应属于 {CORRECT_BASE}/ 目录而非 {WRONG_BASE}/ 目录"
        )

    return violations


# ── CLI 入口 ──────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="文件路径合规检查器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "用法示例:\n"
            "  python -m src.compliance.path_checker --paths src/monitoring/freshness_probe.py\n"
            "  python -m src.compliance.path_checker --paths "
            "C:\\\\Users\\\\17699\\\\mozhi_platform\\\\src\\\\pipeline\\\\main.py "
            "C:\\\\Users\\\\17699\\\\mo_zhi_sharereports\\\\src\\\\wrong.py\n"
            "  echo C:\\\\path\\\\to\\\\file.py | python -m src.compliance.path_checker\n"
        ),
    )
    parser.add_argument(
        "--paths", "-p",
        nargs="*",
        default=None,
        help="要检查的文件路径列表（空格分隔）",
    )
    parser.add_argument(
        "--stdin", "-i",
        action="store_true",
        help="从 stdin 逐行读取路径",
    )

    args = parser.parse_args()

    paths = []

    if args.paths:
        paths.extend(args.paths)

    if args.stdin or (not args.paths and not sys.stdin.isatty()):
        for line in sys.stdin:
            line = line.strip()
            if line:
                paths.append(line)

    if not paths:
        parser.print_help()
        sys.exit(1)

    issues = check_paths(paths)

    if issues:
        print("[FAIL] 路径合规检查发现以下违规：")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print("[PASS] 全部路径合规")
        sys.exit(0)


if __name__ == "__main__":
    main()
