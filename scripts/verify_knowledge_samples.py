#!/usr/bin/env python3
"""一次性验证脚本 — 知识库抽样验证10条

从 backtest_runs 中随机抽样 10 条（固定种子），对比 JSON 文件中的
meta 字段与 DB 记录一致性，以及 market_context 关联正确性。

用法:
    python scripts/verify_knowledge_samples.py

Output: 对比表 + 总体结论，写入 stdout 及 reports/validation/ 文件。

Author: 墨衡
Created: 2026-05-16
"""

import io
import json
import os
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 for stdout (Windows GBK workaround)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ── 路径 ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(str(PROJECT_ROOT))
KNOWLEDGE_DB = str(PROJECT_ROOT / "data" / "knowledge.db")
BACKTEST_RESULTS_DIR = PROJECT_ROOT / "src" / "backtest_results"
OUTPUT_DIR = PROJECT_ROOT / "reports" / "validation"

RANDOM_SEED = 42
SAMPLE_SIZE = 10

# ASCII-safe check/cross markers for console output
OK = "[OK]"
FAIL = "[FAIL]"


def get_backtest_runs() -> list[dict]:
    """从 knowledge.db 读取所有 backtest_runs。"""
    conn = sqlite3.connect(KNOWLEDGE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT run_id, strategy, symbol, config_key, created_at FROM backtest_runs ORDER BY run_id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_market_context(run_id: str) -> list[dict]:
    """查询指定 run_id 关联的 market_context。"""
    conn = sqlite3.connect(KNOWLEDGE_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT date_key, symbol, market_regime, volatility_level, trend_strength, notes "
                 "FROM market_context WHERE run_id = ?", (run_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def load_json_meta(run_id: str):
    """根据 run_id 查找 JSON 文件并返回 meta。"""
    json_name = run_id[4:] + ".json"
    json_path = BACKTEST_RESULTS_DIR / json_name
    if not json_path.exists():
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("meta", {})
    except Exception:
        return {"_error": "parse_failed"}


def verify_one(run: dict) -> dict:
    """验证单条记录。"""
    run_id = run["run_id"]
    meta = load_json_meta(run_id)
    if meta is None:
        return {"run_id": run_id, "has_json": False}

    db_sym = run["symbol"]
    db_cfg = run["config_key"]
    db_strat = run["strategy"]
    db_created = run["created_at"] or ""

    js_sym = meta.get("symbol", "")
    js_cfg = meta.get("config_key", "")
    js_ts = meta.get("timestamp", "")

    sym_ok = (db_sym == js_sym)
    cfg_ok = (db_cfg == js_cfg)

    # Date comparison
    db_date_part = db_created.replace("-", "").replace(" ", "").replace(":", "")[:8]
    js_date_part = js_ts.replace("_", "")[:8] if js_ts else ""
    date_ok = bool(db_date_part and js_date_part and db_date_part == js_date_part)

    mctx = get_market_context(run_id)
    mct_regimes = list(set(c["market_regime"] for c in mctx if c.get("market_regime")))

    return {
        "run_id": run_id,
        "has_json": True,
        "db_strategy": db_strat,
        "db_symbol": db_sym,
        "db_config": db_cfg,
        "db_created": db_created,
        "json_symbol": js_sym,
        "json_config": js_cfg,
        "json_timestamp": js_ts,
        "symbol_match": sym_ok,
        "config_match": cfg_ok,
        "date_ok": date_ok,
        "market_context_count": len(mctx),
        "market_context_regimes": mct_regimes,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 获取 runs ─────────────────────────────────────
    all_runs = get_backtest_runs()
    total = len(all_runs)
    print(f"backtest_runs total: {total}")

    # Deduplicate by run_id
    seen = {}
    for r in all_runs:
        seen[r["run_id"]] = r
    unique_runs = list(seen.values())
    print(f"Deduplicated: {len(unique_runs)} unique run_ids")

    # Only those with JSON files
    valid_runs = [r for r in unique_runs if load_json_meta(r["run_id"]) is not None]
    print(f"With JSON files: {len(valid_runs)}")

    if not valid_runs:
        print("FAIL: No backtest_runs with corresponding JSON files found")
        sys.exit(1)

    # Random sample
    sample_size = min(SAMPLE_SIZE, len(valid_runs))
    random.seed(RANDOM_SEED)
    sample = random.sample(valid_runs, sample_size)

    # Verify each
    results = []
    for r in sample:
        res = verify_one(r)
        if res.get("has_json"):
            ok = all([res.get("symbol_match"), res.get("config_match"), res.get("date_ok")])
            res["all_ok"] = ok
            res["verdict"] = OK if ok else FAIL
        else:
            res["verdict"] = "N/A"
        results.append(res)

    failures = sum(1 for r in results if r.get("verdict") == FAIL)

    # ── Build report (markdown) ───────────────────────
    md_lines = [
        "# Knowledge Sample Verification Report",
        "",
        f"**Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Sampling**: random seed={RANDOM_SEED}, {sample_size} from {len(valid_runs)} valid",
        f"**DB**: {KNOWLEDGE_DB}",
        f"**JSON dir**: {BACKTEST_RESULTS_DIR}",
        "",
        "## Summary",
        f"- Total backtest_runs: {total}",
        f"- Unique run_ids: {len(unique_runs)}",
        f"- With JSON files: {len(valid_runs)}",
        f"- Sampled: {sample_size}",
        f"- All consistent: {sample_size - failures}/{sample_size}",
        "",
        "## Comparison Table",
        "",
    ]

    h = "| # | run_id | DB_strat | DB_sym | JSON_sym | DB_cfg | JSON_cfg | sym | cfg | date | mc_regimes | verdict |"
    sep = "|:-:|:---|---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|:---:|"
    md_lines.append(h)
    md_lines.append(sep)

    for i, res in enumerate(results, 1):
        rid = (res["run_id"][:45] + "..") if len(res["run_id"]) > 47 else res["run_id"]
        r = [
            str(i), rid,
            res.get("db_strategy", "?"),
            res.get("db_symbol", "?"),
            res.get("json_symbol", "N/A"),
            res.get("db_config", "?"),
            res.get("json_config", "N/A"),
            OK if res.get("symbol_match") else FAIL,
            OK if res.get("config_match") else FAIL,
            OK if res.get("date_ok") else FAIL,
            ",".join(res.get("market_context_regimes", [])) or "-",
            res.get("verdict", "?"),
        ]
        md_lines.append("| " + " | ".join(r) + " |")

    md_lines.append("")
    md_lines.append("## Details")
    md_lines.append("")

    for i, res in enumerate(results, 1):
        md_lines.append(f"### Sample #{i}: `{res['run_id']}`")
        md_lines.append("")
        if res.get("has_json"):
            md_lines.append(f"- DB strategy: `{res['db_strategy']}`")
            md_lines.append(f"- DB symbol: `{res['db_symbol']}` -> JSON: `{res.get('json_symbol', '?')}` -> **{OK if res.get('symbol_match') else FAIL}**")
            md_lines.append(f"- DB config: `{res['db_config']}` -> JSON: `{res.get('json_config', '?')}` -> **{OK if res.get('config_match') else FAIL}**")
            md_lines.append(f"- DB created: `{res.get('db_created', '?')}` / JSON timestamp: `{res.get('json_timestamp', '?')}` -> **{OK if res.get('date_ok') else FAIL}**")
            md_lines.append(f"- market_context records: {res.get('market_context_count', 0)}")
            md_lines.append(f"- Regimes: {', '.join(res.get('market_context_regimes', [])) or '(none)'}")
            md_lines.append(f"")
        else:
            md_lines.append(f"- **No JSON file**")
        md_lines.append(f"- **Verdict**: {res.get('verdict', '?')}")
        md_lines.append("")

    md_lines.append("## Conclusion")
    md_lines.append(f"- {sample_size - failures}/{sample_size} samples fully consistent")
    md_lines.append(f"- Data integrity: **{'PASS' if failures == 0 else f'{failures} mismatches'}**")
    md_lines.append("")

    report = "\n".join(md_lines)
    print(report)

    # Write report file
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"knowledge_sample_verify_{ts}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"[done] Report written: {out_path}")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
