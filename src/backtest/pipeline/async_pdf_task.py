#!/usr/bin/env python3
"""
墨枢 — P7: 异步 PDF 生成后台任务
==================================
Step4.5 只生成 HTML，PDF 交由此后台 subprocess 异步生成。
使用 Edge (Chromium) headless 模式将 HTML 转为 PDF。

设计要点
--------
- 通过 subprocess 调用 Edge headless 进程，不阻塞管线
- Edge 路径自动检测（优先 %PATH% 中的 msedge，降级至 Program Files）
- 写入防碰撞（P8: 前缀加 timestamp，同秒冲突自动 retry）
- 超时保护（P9: 默认 60s 超时）

用法::

    # 直接调用
    python async_pdf_task.py --input report.html --output report.pdf

    # Python 入口
    from backtest.pipeline.async_pdf_task import generate_pdf_async

    task_id = generate_pdf_async(input_html, output_pdf)

Author: 墨衡
Created: 2026-05-16
"""

import os
import sys
import json
import time
import argparse
import logging
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AsyncPDF")

# ── Edge 可执行文件路径检测 ────────────────────────────

_EDGE_CANDIDATES = [
    "msedge",                          # %PATH% 或同目录
    "msedge.exe",
    # 常见安装路径
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
]


def _find_edge() -> Optional[str]:
    """查找 Edge 可执行文件路径"""
    for candidate in _EDGE_CANDIDATES:
        # 先查 PATH
        if candidate in ("msedge", "msedge.exe"):
            try:
                result = subprocess.run(
                    ["where", candidate] if sys.platform == "win32" else ["which", "microsoft-edge"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    path = result.stdout.strip().splitlines()[0]
                    if os.path.isfile(path):
                        logger.info(f"[find_edge] 找到: {path}")
                        return path
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        else:
            if os.path.isfile(candidate):
                logger.info(f"[find_edge] 找到: {candidate}")
                return candidate
    logger.warning("[find_edge] 未找到 Edge 可执行文件")
    return None


# ═══════════════════════════════════════════════════════════════
# P8: 文件名防碰撞
# ═══════════════════════════════════════════════════════════════

def _safe_pdf_path(output_path: str, max_retries: int = 5) -> str:
    """生成防碰撞 PDF 路径: 加 timestamp 前缀，同秒冲突自动 retry"""
    base = Path(output_path)
    parent = base.parent
    stem = base.stem
    ext = base.suffix or ".pdf"

    for attempt in range(max_retries):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:23]  # 含微秒
        out_name = f"{stem}_{ts}{ext}"
        out_path = str(parent / out_name)
        if not os.path.exists(out_path):
            return out_path
        # 同秒冲突: 微秒 + 1 重试
        time.sleep(0.05)
    # 最终降级：加随机数
    import random
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    rand = random.randint(1000, 9999)
    out_name = f"{stem}_{ts}_{rand}{ext}"
    return str(parent / out_name)


# ═══════════════════════════════════════════════════════════════
# PDF 生成核心
# ═══════════════════════════════════════════════════════════════

def generate_pdf(
    input_html: str,
    output_pdf: str,
    timeout_seconds: int = 60,
    on_progress: Optional[Callable] = None,
) -> bool:
    """同步将 HTML 转为 PDF（Edge headless 模式）。

    Args:
        input_html: HTML 文件路径
        output_pdf: PDF 输出路径
        timeout_seconds: 超时秒数（默认 60）
        on_progress: 进度回调

    Returns:
        bool: True 成功, False 失败
    """
    if not os.path.isfile(input_html):
        logger.error(f"[pdf] HTML 文件不存在: {input_html}")
        return False

    edge_path = _find_edge()
    if not edge_path:
        logger.error("[pdf] 未找到 Edge（Chromium），无法生成 PDF")
        return False

    # P8: 防碰撞输出路径
    safe_output = _safe_pdf_path(output_pdf)

    abs_html = os.path.abspath(input_html)
    abs_output = os.path.abspath(safe_output)

    cmd = [
        edge_path,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        f"--print-to-pdf={abs_output}",
        f"file:///{abs_html.replace(os.sep, '/').lstrip('/')}",
    ]

    logger.info(f"[pdf] 启动: {' '.join(cmd)}")
    if on_progress:
        on_progress("generating")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if result.returncode == 0 and os.path.isfile(abs_output) and os.path.getsize(abs_output) > 0:
            size_kb = os.path.getsize(abs_output) / 1024
            logger.info(f"[pdf] 生成成功: {abs_output} ({size_kb:.1f} KB)")
            # 如果原路径与安全路径不同，复制回原路径
            if safe_output != output_pdf:
                import shutil
                shutil.copy2(abs_output, output_pdf)
                logger.info(f"[pdf] 已复制到原始路径: {output_pdf}")
            if on_progress:
                on_progress("done")
            return True
        else:
            stderr = result.stderr[:500] if result.stderr else "(no output)"
            logger.warning(f"[pdf] Edge 返回非零: rc={result.returncode}, stderr={stderr}")
            if on_progress:
                on_progress("failed")
            return False
    except subprocess.TimeoutExpired:
        logger.warning(f"[pdf] 超时 {timeout_seconds}s: {input_html}")
        if on_progress:
            on_progress("timeout")
        return False
    except Exception as e:
        logger.error(f"[pdf] 异常: {e}")
        if on_progress:
            on_progress("error")
        return False


# ═══════════════════════════════════════════════════════════════
# 异步 PDF 后台任务（线程）
# ═══════════════════════════════════════════════════════════════

def generate_pdf_async(
    input_html: str,
    output_pdf: str,
    timeout_seconds: int = 60,
    callback: Optional[Callable[[bool, str], None]] = None,
) -> threading.Thread:
    """启动后台线程生成 PDF，不阻塞调用方。

    Args:
        input_html: HTML 文件路径
        output_pdf: PDF 输出路径
        timeout_seconds: 超时秒数
        callback: (success: bool, output_path: str) 回调函数

    Returns:
        threading.Thread: 后台线程句柄
    """

    def _worker():
        success = generate_pdf(input_html, output_pdf, timeout_seconds)
        if callback:
            callback(success, output_pdf)

    thread = threading.Thread(target=_worker, daemon=True, name="AsyncPDF")
    thread.start()
    logger.info(f"[async_pdf] 后台任务已启动: input={input_html}, output={output_pdf}")
    return thread


# ═══════════════════════════════════════════════════════════════
# 结果标记文件写入
# ═══════════════════════════════════════════════════════════════

def write_pdf_result(task_id: str, status: str, input_html: str, output_pdf: str):
    """将 PDF 生成结果写入 signals/tasks/ 下"""
    from src.config import SIGNALS_TASKS_DIR

    result = {
        "task_id": f"{task_id}_pdf",
        "status": status,
        "input_html": input_html,
        "output_pdf": output_pdf,
        "completed_time": datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }
    path = SIGNALS_TASKS_DIR / f"{task_id}_pdf_result.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"[pdf_result] 结果已写入: {path}")


# ═══════════════════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="异步 PDF 生成（Edge headless）")
    parser.add_argument("--input", required=True, help="输入 HTML 文件路径")
    parser.add_argument("--output", required=True, help="输出 PDF 文件路径")
    parser.add_argument("--timeout", type=int, default=60, help="超时秒数（默认 60）")
    parser.add_argument("--task-id", default="", help="task_id（用于写结果标记）")
    args = parser.parse_args()

    success = generate_pdf(
        input_html=args.input,
        output_pdf=args.output,
        timeout_seconds=args.timeout,
    )

    if args.task_id:
        write_pdf_result(
            task_id=args.task_id,
            status="READY" if success else "FAILED",
            input_html=args.input,
            output_pdf=args.output,
        )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
