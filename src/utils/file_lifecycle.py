"""
file_lifecycle.py — 文件生命周期管理系统 v3

架构升级：
- category 标准化为固定 9 枚举 (automation|backtest|reports|docs|signals|tools|db|agents|shared)
- status 标准化为固定 6 枚举 (incoming|experimental|staging|production|deprecated|archived)
- 新增 current_path 列（保留 original_path 不变，current_path 随文件移动更新）
- 新增 checksum 列（SHA256 hex digest）
- 新增 source_type 列 (ai_chatgpt|ai_deepseek|manual|imported|migrated|unknown)
- 自动 note 摘要提取（daily-maintenance）

作者: moheng
创建时间: 2026-05-15
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 项目根目录自动探测
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # mozhi_platform/
REGISTRY_DIR = PROJECT_ROOT / "data" / "registry"
DB_PATH = REGISTRY_DIR / "file_registry.db"
INCOMING_BASE = PROJECT_ROOT / "incoming"

# 只读存档仓库路径（第二个仓库）
ARCHIVE_BASE = Path(r"C:\Users\17699\mo_zhi_sharereports")

TIMEZONE = "+08:00"

# ─── 标准化枚举 ──────────────────────────────────────────────

# 固定 category 枚举（业务归属）
VALID_CATEGORIES = [
    "automation", "backtest", "reports", "docs", "signals",
    "tools", "db", "agents", "shared",
]

# 固定 status 枚举（生命周期）
VALID_STATUSES = [
    "incoming", "experimental", "staging", "production",
    "deprecated", "archived",
]

# 有效 source 枚举（物理来源）
VALID_SOURCES = ["incoming", "platform", "archive"]

# 有效 source_type 枚举
VALID_SOURCE_TYPES = [
    "ai_chatgpt", "ai_deepseek", "manual", "imported", "migrated", "unknown",
]

# ─── 分类映射字典 ────────────────────────────────────────────

CATEGORY_MAP = {
    'automation_v2':       'automation',
    'agents':              'agents',
    'archive':             'shared',
    'backtest_engine':     'backtest',
    'backtest_results':    'backtest',
    'bots':                'automation',
    'code':                'automation',
    'collectors':          'tools',
    'comm_status':         'shared',
    'config':              'tools',
    'daily':               'reports',
    'data':                'db',
    'data_warehouse':      'db',
    'db':                  'db',
    'deploy':              'tools',
    'docs':                'docs',
    'docs/':               'docs',
    'eventbus':            'signals',
    'experiments':         'backtest',
    'hotspot':             'reports',
    'incoming/':           'shared',
    'knowledge_base':      'shared',
    'lib':                 'shared',
    'locks':               'shared',
    'logs':                'shared',
    'meeting':             'shared',
    'memory':              'shared',
    'mozhi_share_lib':     'shared',
    'not_found':           'shared',
    'oil_price_monitor':   'reports',
    'p0_tasks':            'docs',
    'pgsql':               'db',
    'phase1_core':         'automation',
    'phase_2_2_adapter':   'automation',
    'pipeline':            'automation',
    'report_pipeline':     'reports',
    'reports':             'reports',
    'reviews':             'reports',
    'rollback':            'shared',
    'runtime':             'shared',
    'scheduler':           'automation',
    'scripts':             'tools',
    'shared':              'shared',
    'signals':             'signals',
    'signons':             'shared',
    'skills':              'tools',
    'templates':           'shared',
    'tests':               'backtest',
    'test_sandbox':        'backtest',
    'token_optimizer':     'tools',
    'tools':               'tools',
    'ui':                  'tools',
    'unit_tests':          'backtest',
    'workflows':           'automation',
    'workspace_mochen':    'shared',
    'xuanzhi_merge':       'tools',
    '601857_analysis':     'reports',
    'cache_manager':       'tools',
}

# 常用关键词 → 标准化分类（用于 meta target 字段匹配）
KEYWORD_CATEGORY_MAP = {
    "automation": "automation",
    "backtest":   "backtest",
    "ta_":        "backtest",
    "document":   "docs",
    "doc":        "docs",
    "tool":       "tools",
    "trading":    "shared",
    "trade":      "shared",
    "data":       "db",
    "config":     "tools",
    "conf":       "tools",
    "report":     "reports",
    "script":     "tools",
    "archive":    "shared",
    "agent":      "agents",
    "signal":     "signals",
    "pipeline":   "automation",
    "scheduler":  "automation",
    "workflow":   "automation",
    "test":       "backtest",
    "experiment": "backtest",
}

# ─── DDL ─────────────────────────────────────────────────────

DDL_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT,
    original_path TEXT,
    current_path TEXT,
    category TEXT,
    source TEXT NOT NULL DEFAULT 'incoming',
    status TEXT,
    checksum TEXT,
    source_type TEXT NOT NULL DEFAULT 'unknown',
    created_at TEXT,
    imported_at TEXT,
    tags TEXT,
    note TEXT
);
"""

DDL_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_files_original_path ON files(original_path);
"""

DDL_INDEX_FILENAME = """
CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);
"""

DDL_INDEX_SOURCE = """
CREATE INDEX IF NOT EXISTS idx_files_source ON files(source);
"""

DDL_INDEX_CATEGORY = """
CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
"""

DDL_INDEX_STATUS = """
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
"""

DDL_INDEX_CURRENT_PATH = """
CREATE INDEX IF NOT EXISTS idx_files_current_path ON files(current_path);
"""

DDL_INDEX_SOURCE_TYPE = """
CREATE INDEX IF NOT EXISTS idx_files_source_type ON files(source_type);
"""


# ─── 辅助函数 ────────────────────────────────────────────────


def now_str() -> str:
    """返回带时区的当前时间字符串（YYYY-MM-DD HH:MM）。"""
    return datetime.now().strftime(f"%Y-%m-%d %H:%M")


def get_db() -> sqlite3.Connection:
    """获取数据库连接，自动创建表和索引。"""
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(DDL_CREATE_TABLE)
    for ddl_index in [
        DDL_UNIQUE_INDEX, DDL_INDEX_FILENAME, DDL_INDEX_SOURCE,
        DDL_INDEX_CATEGORY, DDL_INDEX_STATUS,
        DDL_INDEX_CURRENT_PATH, DDL_INDEX_SOURCE_TYPE,
    ]:
        try:
            conn.execute(ddl_index)
        except sqlite3.OperationalError:
            pass  # 索引已存在
    return conn


def ensure_db():
    """确保数据库和表存在（用于初始化）。"""
    get_db().close()


def rebuild_db():
    """重建数据库表（DROP + CREATE），用于结构变更后重建。"""
    conn = get_db()
    try:
        conn.execute("DROP TABLE IF EXISTS files")
        conn.execute(DDL_CREATE_TABLE)
        for ddl_index in [
            DDL_UNIQUE_INDEX, DDL_INDEX_FILENAME, DDL_INDEX_SOURCE,
            DDL_INDEX_CATEGORY, DDL_INDEX_STATUS,
            DDL_INDEX_CURRENT_PATH, DDL_INDEX_SOURCE_TYPE,
        ]:
            try:
                conn.execute(ddl_index)
            except sqlite3.OperationalError:
                pass
        conn.commit()
        print(f"[OK] 数据库重建完成: {DB_PATH}")
    finally:
        conn.close()


def compute_checksum(filepath: Path) -> str:
    """计算文件的 SHA256 hex digest。"""
    sha256 = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except (OSError, PermissionError):
        return ""


def extract_summary(filepath: Path, max_len: int = 80) -> str:
    """自动提取文件内容摘要，用于 note 填充。

    按文件类型提取：
    - .py: 首个注释/docstring
    - .md: 首个 # 标题
    - .json: 解析后取 description/key 字段
    - .yaml/.yml: 首个注释或 name 字段
    - .csv: 第一行前4列
    - 其他: 空字符串
    """
    try:
        suffix = filepath.suffix.lower()
        raw = filepath.read_bytes()
        # 尝试用 utf-8 读取，失败则用 latin-1
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="replace")

        if suffix == ".py":
            return _extract_py_summary(text, max_len)
        elif suffix == ".md":
            return _extract_md_summary(text, max_len)
        elif suffix == ".json":
            return _extract_json_summary(text, max_len)
        elif suffix in (".yaml", ".yml"):
            return _extract_yaml_summary(text, max_len)
        elif suffix == ".csv":
            return _extract_csv_summary(text, max_len)
        else:
            return ""
    except Exception:
        return ""


def _extract_py_summary(text: str, max_len: int) -> str:
    """提取 Python 文件的首个注释或 docstring。"""
    lines = text.split("\n")
    i = 0
    # 跳过空行和 shebang
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#!"):
            i += 1
            continue
        break

    if i >= len(lines):
        return ""

    stripped = lines[i].strip()

    # 单行注释
    if stripped.startswith("#"):
        return stripped.lstrip("#").strip()[:max_len]

    # docstring (""" 或 ''')
    if stripped.startswith('"""') or stripped.startswith("'''"):
        delim = stripped[:3]
        rest = stripped[3:]
        # 单行 docstring
        if delim in rest:
            end_idx = rest.index(delim)
            return rest[:end_idx].strip()[:max_len]
        # 多行 docstring：收集后续行直到结束
        doc_lines = [rest]
        i += 1
        while i < len(lines):
            line = lines[i]
            if delim in line:
                end_idx = line.index(delim)
                doc_lines.append(line[:end_idx])
                break
            doc_lines.append(line)
            i += 1
        result = " ".join(l.strip() for l in doc_lines if l.strip())
        return result[:max_len] if result else ""

    # 如果第一行非空行是 import/from/class/def，说明没有顶部注释
    if any(stripped.startswith(kw) for kw in ("import", "from", "class", "def", "@")):
        return ""

    return ""


def _extract_md_summary(text: str, max_len: int) -> str:
    """提取 Markdown 文件的首个 # 标题。"""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:max_len]
        if stripped.startswith("#"):
            # ## ### 等
            level = len(stripped) - len(stripped.lstrip("#"))
            if stripped[level:].startswith(" "):
                return stripped[level + 1:].strip()[:max_len]
    return ""


def _extract_json_summary(text: str, max_len: int) -> str:
    """提取 JSON 的 description 或首个 key。"""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            if "description" in data and isinstance(data["description"], str):
                return data["description"][:max_len]
            # 取首个有价值的 key
            keys = [k for k in data.keys() if not k.startswith("_")]
            if keys:
                return keys[0][:max_len]
        return ""
    except (json.JSONDecodeError, ValueError):
        return ""


def _extract_yaml_summary(text: str, max_len: int) -> str:
    """提取 YAML 文件的首个注释或 name 字段。"""
    lines = text.split("\n")
    # 找首个 # 注释
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:max_len]
    # 找 name: 字段
    for line in lines:
        if line.strip().lower().startswith("name:"):
            val = line.split(":", 1)[1].strip().strip("'\"")
            return val[:max_len]
    return ""


def _extract_csv_summary(text: str, max_len: int) -> str:
    """提取 CSV 文件第一行的前4列。"""
    first_line = text.split("\n")[0].strip()
    if not first_line:
        return ""
    cols = first_line.split(",")[:4]
    result = ", ".join(c.strip() for c in cols)
    return result[:max_len]


def map_target_to_category(target: str) -> str:
    """将 target/directory 字段映射到标准化分类。

    优先级：
    1. 精确匹配 CATEGORY_MAP（规范化后）
    2. CATEGORY_MAP 关键词匹配（按 key 长度降序）
    3. KEYWORD_CATEGORY_MAP 常用词匹配
    4. 标准化 category 枚举值匹配
    5. 默认 'shared'
    """
    target_lower = target.lower().strip().replace("-", "_").replace("/", "_").replace("\\", "_")
    clean = target_lower.rstrip("_").lstrip("_")

    # 1. 精确匹配 CATEGORY_MAP
    if clean in CATEGORY_MAP:
        return CATEGORY_MAP[clean]

    # 2. CATEGORY_MAP 关键词匹配
    for key in sorted(CATEGORY_MAP.keys(), key=len, reverse=True):
        if key in target_lower:
            return CATEGORY_MAP[key]

    # 3. KEYWORD_CATEGORY_MAP 匹配
    for keyword in sorted(KEYWORD_CATEGORY_MAP.keys(), key=len, reverse=True):
        if keyword in target_lower:
            return KEYWORD_CATEGORY_MAP[keyword]

    # 4. 标准化 category 枚举值匹配
    for cat in sorted(VALID_CATEGORIES, key=len, reverse=True):
        if cat in target_lower:
            return cat

    # 5. 默认
    return "shared"


# ─── 核心功能 ───────────────────────────────────────────────


def register_incoming(
    date_str: Optional[str] = None,
    verbose: bool = True,
    dry_run: bool = False,
) -> int:
    """
    扫描 incoming 目录，将所有有 .meta.json 的数据文件登记到数据库。

    参数:
        date_str: YYYYMMDD 格式日期，None 扫描所有日期子目录。
        verbose: 输出详细信息。
        dry_run: 仅显示将登记哪些文件，不实际写入。

    返回:
        新增登记的文件数。
    """
    if not INCOMING_BASE.exists():
        if verbose:
            print(f"[SKIP] incoming 目录不存在: {INCOMING_BASE}")
        return 0

    # 确定要扫描的子目录
    if date_str:
        dirs_to_scan = [INCOMING_BASE / date_str]
        if not dirs_to_scan[0].exists():
            print(f"[ERROR] 目录不存在: {dirs_to_scan[0]}", file=sys.stderr)
            return 0
    else:
        dirs_to_scan = sorted(
            [d for d in INCOMING_BASE.iterdir() if d.is_dir()]
        )

    if not dirs_to_scan:
        if verbose:
            print(f"[SKIP] incoming 下无日期子目录")
        return 0

    conn = get_db()
    registered = 0
    skipped = 0

    try:
        for dir_path in dirs_to_scan:
            if verbose:
                print(f"[SCAN] {dir_path.name}/")

            # 收集所有 .meta.json 文件
            meta_files = sorted(dir_path.glob("*.meta.json"))
            for meta_path in meta_files:
                # 计算对应的数据文件名
                meta_stem = meta_path.stem  # e.g. "fix_settlement.meta" → "fix_settlement.meta"
                data_filename = meta_stem
                if data_filename.endswith(".meta"):
                    data_filename = data_filename[:-5]  # 去掉 .meta
                data_path = dir_path / data_filename

                # 检查数据文件是否存在
                if not data_path.exists():
                    if verbose:
                        print(f"  [WARN] 数据文件不存在: {data_path.name} (meta 孤立)")
                    continue

                # 读取 .meta.json
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    if verbose:
                        print(f"  [ERR] 读取 meta 失败: {meta_path.name}: {e}")
                    continue

                # 检查是否已登记（按 original_path 去重）
                original_path = str(data_path.resolve())
                cursor = conn.execute(
                    "SELECT id FROM files WHERE original_path = ?",
                    (original_path,),
                )
                if cursor.fetchone():
                    skipped += 1
                    if verbose:
                        print(f"  [SKIP] 已登记: {data_path.name}")
                    continue

                # 映射 meta 字段到数据库
                created_at = meta.get("created_at", "")
                meta_source = meta.get("source", "")
                status = meta.get("status", "incoming")
                target = meta.get("target", "unassigned")
                description = meta.get("description", "")
                owner = meta.get("owner", "unassigned")

                # 确定分类
                category = map_target_to_category(target)

                # 计算 checksum
                checksum = compute_checksum(data_path)

                # 构建标签
                tags_parts = [meta_source] if meta_source else []
                if target and target != "unassigned":
                    tags_parts.append(target)
                if owner and owner != "unassigned":
                    tags_parts.append(owner)
                tags = ",".join(tags_parts) if tags_parts else "incoming"

                # 备注：优先使用 description
                if description:
                    note = description
                elif meta_source:
                    note = f"来源: {meta_source}"
                else:
                    note = ""

                if dry_run:
                    if verbose:
                        print(f"  [WOULD] 登记: {data_path.name} → {category}")
                    continue

                # 写入数据库
                conn.execute(
                    """INSERT INTO files
                       (filename, original_path, current_path, category, source, status,
                        checksum, source_type, created_at, imported_at, tags, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        data_path.name,
                        original_path,
                        original_path,  # current_path 初始 = original_path
                        category,
                        "incoming",
                        status,
                        checksum,
                        "unknown",  # source_type: 等待更新
                        created_at,
                        now_str(),
                        tags,
                        note,
                    ),
                )
                registered += 1
                if verbose:
                    print(f"  [REG] 登记: {data_path.name} ({category}) [checksum={checksum[:12]}...]")

            if not any(dir_path.glob("*.meta.json")):
                if verbose:
                    print(f"  (无 meta 文件)")

        if not dry_run:
            conn.commit()

    finally:
        conn.close()

    if verbose:
        print(f"\n[SUMMARY] 新增: {registered} | 跳过(已存在): {skipped}")

    return registered


def archive_scan(
    verbose: bool = True,
    dry_run: bool = False,
) -> int:
    """
    扫描 ARCHIVE_BASE (mo_zhi_sharereports/) 全目录，登记到 registry。

    排除目录：signals/, .git/, __pycache__/
    使用 CATEGORY_MAP 标准化分类。
    跳过已有记录（按 original_path 去重）。

    参数:
        verbose: 输出详细信息。
        dry_run: 仅模拟，不实际写入。

    返回:
        新增登记的文件数。
    """
    if not ARCHIVE_BASE.exists():
        print(f"[ERROR] archive 目录不存在: {ARCHIVE_BASE}", file=sys.stderr)
        return 0

    # 排除目录名集合（signals 不再排除，需要登记）
    EXCLUDE_DIRS = {".git", "__pycache__", ".github", ".pytest_cache", "node_modules"}

    # 扫描所有文件
    all_files = []
    for root, dirs, files in os.walk(str(ARCHIVE_BASE)):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            full_path = Path(root) / f
            if f.startswith("."):
                continue
            if f.endswith(".meta.json"):
                continue
            all_files.append(full_path)

    total = len(all_files)
    if verbose:
        print(f"[SCAN] 发现 {total} 个文件")

    if total == 0:
        print(f"[SKIP] archive 无文件需要扫描")
        return 0

    conn = get_db()
    registered = 0
    skipped = 0

    try:
        # 预计算顶部目录分布
        top_dirs = {}
        for fp in all_files:
            try:
                rel = fp.relative_to(ARCHIVE_BASE)
                top = rel.parts[0] if rel.parts else "shared"
            except ValueError:
                top = "shared"
            if top in EXCLUDE_DIRS:
                continue
            top_dirs.setdefault(top, []).append(fp)

        sorted_dirs = sorted(top_dirs.items(), key=lambda x: len(x[1]), reverse=True)

        if verbose:
            print(f"\n  目录分布 (使用标准化分类):")
            print(f"  {'目录':<24} {'数量':>6}")
            print(f"  {'-'*32}")
            for i, (dirname, flist) in enumerate(sorted_dirs[:20], 1):
                cat = map_target_to_category(dirname)
                print(f"  #{i:<2} {dirname:<20} {len(flist):>6} (→ {cat})")
            if len(sorted_dirs) > 20:
                print(f"  ... 及其他 {len(sorted_dirs) - 20} 个目录")
            print()

        processed = 0
        for fp in all_files:
            processed += 1
            original_path = str(fp.resolve())

            cursor = conn.execute(
                "SELECT id FROM files WHERE original_path = ?",
                (original_path,),
            )
            if cursor.fetchone():
                skipped += 1
                continue

            # 确定标准化分类
            try:
                rel = fp.relative_to(ARCHIVE_BASE)
                top = rel.parts[0] if rel.parts else "shared"
            except ValueError:
                top = "shared"
            category = map_target_to_category(top)

            # 获取文件创建时间
            try:
                stat = fp.stat()
                created_dt = datetime.fromtimestamp(stat.st_ctime)
                created_at = created_dt.strftime(f"%Y-%m-%d %H:%M")
            except OSError:
                created_at = now_str()

            # 计算 checksum
            checksum = compute_checksum(fp)

            # 构建标签和备注
            tags = f"archive,{top}"
            note = f"来源: archive/{top}"

            if dry_run:
                if verbose and processed % 100 == 1:
                    print(f"  [WOULD] {processed}/{total}: {fp.name} → {category}")
                continue

            # 写入数据库
            conn.execute(
                """INSERT INTO files
                   (filename, original_path, current_path, category, source, status,
                    checksum, source_type, created_at, imported_at, tags, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fp.name,
                    original_path,
                    str(fp),
                    category,
                    "archive",
                    "archived",
                    checksum,
                    "migrated",
                    created_at,
                    now_str(),
                    tags,
                    note,
                ),
            )
            registered += 1

            if verbose and processed % 100 == 0:
                print(f"  [PROGRESS] 已处理 {processed}/{total} 文件 (checksum calcd)")

        if not dry_run:
            conn.commit()

    finally:
        conn.close()

    if verbose:
        print(f"\n[SUMMARY] 新增: {registered} | 跳过(已存在): {skipped} | 总计: {total}")

    return registered


def daily_maintenance(
    verbose: bool = True,
    dry_run: bool = False,
    date_str: Optional[str] = None,
) -> dict:
    """
    每日维护：扫描 incoming/ 下所有文件，
    自动生成缺失的 .meta.json，登记到 DB，
    并自动提取文件摘要填入 note。

    参数:
        verbose: 输出详细信息。
        dry_run: 仅模拟，不实际写入。
        date_str: 指定日期 (YYYYMMDD)，None 则处理所有日期目录。

    返回:
        汇总报告字典。
    """
    if not INCOMING_BASE.exists():
        if verbose:
            print(f"[SKIP] incoming 目录不存在: {INCOMING_BASE}")
        return {"files_scanned": 0, "meta_generated": 0, "registered": 0, "categories": {}}

    if date_str:
        dirs_to_scan = [INCOMING_BASE / date_str]
        if not dirs_to_scan[0].exists():
            print(f"[ERROR] 目录不存在: {dirs_to_scan[0]}", file=sys.stderr)
            return {"files_scanned": 0, "meta_generated": 0, "registered": 0, "categories": {}}
    else:
        dirs_to_scan = sorted(
            [d for d in INCOMING_BASE.iterdir() if d.is_dir()]
        )

    if not dirs_to_scan:
        if verbose:
            print(f"[SKIP] incoming 下无子目录")
        return {"files_scanned": 0, "meta_generated": 0, "registered": 0, "categories": {}}

    conn = get_db()
    files_scanned = 0
    meta_generated = 0
    registered = 0
    category_counts = {}

    try:
        for dir_path in dirs_to_scan:
            date_part = dir_path.name
            if verbose:
                print(f"[SCAN] {date_part}/")

            all_items = sorted(dir_path.iterdir())
            data_files = []
            for item in all_items:
                if item.is_dir():
                    continue
                if item.name.startswith("."):
                    continue
                if item.name.endswith(".meta.json"):
                    continue
                data_files.append(item)

            for data_path in data_files:
                files_scanned += 1
                expected_meta = dir_path / f"{data_path.name}.meta.json"
                has_meta = expected_meta.exists()

                if not has_meta:
                    auto_meta = {
                        "created_at": now_str(),
                        "source": "incoming",
                        "status": "incoming",
                        "target": "unassigned",
                        "owner": "auto",
                        "description": f"每日维护自动生成 - {data_path.name}",
                    }
                    if not dry_run:
                        expected_meta.write_text(
                            json.dumps(auto_meta, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        meta_generated += 1
                        if verbose:
                            print(f"  [AUTO-META] 生成: {data_path.name}.meta.json")
                    else:
                        if verbose:
                            print(f"  [WOULD] 生成 meta: {data_path.name}.meta.json")

                original_path = str(data_path.resolve())
                cursor = conn.execute(
                    "SELECT id FROM files WHERE original_path = ?",
                    (original_path,),
                )
                if cursor.fetchone():
                    continue

                try:
                    with open(expected_meta, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except (json.JSONDecodeError, OSError) as e:
                    if verbose:
                        print(f"  [ERR] 读取 meta 失败: {expected_meta.name}: {e}")
                    continue

                created_at = meta.get("created_at", now_str())
                status = meta.get("status", "incoming")
                target = meta.get("target", "unassigned")
                owner = meta.get("owner", "unassigned")
                description = meta.get("description", "")

                category = map_target_to_category(target)
                category_counts[category] = category_counts.get(category, 0) + 1

                # 计算 checksum
                checksum = compute_checksum(data_path)

                tags_parts = ["incoming"]
                if target and target != "unassigned":
                    tags_parts.append(target)
                if owner and owner != "unassigned":
                    tags_parts.append(owner)
                tags = ",".join(tags_parts)

                # 自动提取摘要作为 note
                auto_note = extract_summary(data_path)
                note = description if description else (auto_note or f"每日维护 - {date_part}")

                if dry_run:
                    if verbose:
                        print(f"  [WOULD] 登记: {data_path.name} → {category}")
                    continue

                conn.execute(
                    """INSERT INTO files
                       (filename, original_path, current_path, category, source, status,
                        checksum, source_type, created_at, imported_at, tags, note)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        data_path.name,
                        original_path,
                        original_path,
                        category,
                        "incoming",
                        status,
                        checksum,
                        "unknown",
                        created_at,
                        now_str(),
                        tags,
                        note,
                    ),
                )
                registered += 1
                if verbose:
                    print(f"  [REG] 登记: {data_path.name} ({category})")

        if not dry_run:
            conn.commit()

    finally:
        conn.close()

    report = {
        "files_scanned": files_scanned,
        "meta_generated": meta_generated,
        "registered": registered,
        "categories": dict(sorted(category_counts.items(), key=lambda x: -x[1])),
        "unassigned_count": category_counts.get("shared", 0),
        "status": "success" if not dry_run else "dry_run",
    }

    if verbose:
        print(f"\n{'='*50}")
        print(f"  每日维护汇总")
        print(f"{'='*50}")
        print(f"  扫描文件数:       {files_scanned}")
        print(f"  自动生成 meta:    {meta_generated}")
        print(f"  新登记记录数:     {registered}")
        print()
        if category_counts:
            print(f"  按分类分布:")
            for cat, cnt in sorted(category_counts.items(), key=lambda x: -x[1]):
                print(f"    {cat:<20} {cnt:>6}")
        if report["unassigned_count"] > 0:
            print(f"\n  ⚠️  未分类文件数: {report['unassigned_count']}")
            print(f"  建议使用 'update' 子命令为未分类文件指定分类")
        print(f"\n{'='*50}\n")

    return report


def scan_registry(verbose: bool = True) -> dict:
    """
    扫描 registry 数据库，生成统计报告。

    参数:
        verbose: 是否打印报告。

    返回:
        包含统计数据的字典。
    """
    ensure_db()
    conn = get_db()
    report = {}

    try:
        cursor = conn.execute("SELECT COUNT(*) as total FROM files")
        total = cursor.fetchone()["total"]
        report["total"] = total
        if verbose:
            print(f"\n{'='*50}")
            print(f"  注册库统计报告")
            print(f"{'='*50}")
            print(f"  总记录数: {total}")
            print()

        print(f"  按来源分布:")
        print(f"  {'来源':<12} {'数量':>6} {'占比':>8}")
        print(f"  {'-'*28}")
        cursor = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM files GROUP BY source ORDER BY cnt DESC"
        )
        source_dist = {}
        for row in cursor.fetchall():
            s = row["source"] or "unknown"
            cnt = row["cnt"]
            pct = f"{cnt / total * 100:.1f}%" if total > 0 else "0%"
            source_dist[s] = cnt
            if verbose:
                print(f"  {s:<12} {cnt:>6} {pct:>8}")
        report["source_distribution"] = source_dist
        if verbose:
            print()

        print(f"  按状态分布:")
        print(f"  {'状态':<12} {'数量':>6} {'占比':>8}")
        print(f"  {'-'*28}")
        cursor = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM files GROUP BY status ORDER BY cnt DESC"
        )
        status_dist = {}
        for row in cursor.fetchall():
            s = row["status"] or "unknown"
            cnt = row["cnt"]
            pct = f"{cnt / total * 100:.1f}%" if total > 0 else "0%"
            status_dist[s] = cnt
            if verbose:
                print(f"  {s:<12} {cnt:>6} {pct:>8}")
        report["status_distribution"] = status_dist
        if verbose:
            print()

        print(f"  按分类分布 (标准化):")
        print(f"  {'分类':<16} {'数量':>6} {'占比':>8}")
        print(f"  {'-'*32}")
        cursor = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM files GROUP BY category ORDER BY cnt DESC"
        )
        cat_dist = {}
        for row in cursor.fetchall():
            c = row["category"] or "unclassified"
            cnt = row["cnt"]
            pct = f"{cnt / total * 100:.1f}%" if total > 0 else "0%"
            cat_dist[c] = cnt
            if verbose:
                print(f"  {c:<16} {cnt:>6} {pct:>8}")
        report["category_distribution"] = cat_dist
        if verbose:
            print()

        print(f"  按 source_type 分布:")
        print(f"  {'Source Type':<16} {'数量':>6} {'占比':>8}")
        print(f"  {'-'*32}")
        cursor = conn.execute(
            "SELECT source_type, COUNT(*) as cnt FROM files GROUP BY source_type ORDER BY cnt DESC"
        )
        st_dist = {}
        for row in cursor.fetchall():
            st = row["source_type"] or "unknown"
            cnt = row["cnt"]
            pct = f"{cnt / total * 100:.1f}%" if total > 0 else "0%"
            st_dist[st] = cnt
            if verbose:
                print(f"  {st:<16} {cnt:>6} {pct:>8}")
        report["source_type_distribution"] = st_dist
        if verbose:
            print()

        print(f"  孤儿文件检查:")
        cursor = conn.execute(
            "SELECT id, filename, original_path, status FROM files WHERE status != 'deleted'"
        )
        orphans = []
        for row in cursor.fetchall():
            fp = Path(row["original_path"])
            if not fp.exists():
                orphans.append({
                    "id": row["id"],
                    "filename": row["filename"],
                    "original_path": row["original_path"],
                    "status": row["status"],
                })
        report["orphans"] = orphans
        if verbose:
            if orphans:
                print(f"  ⚠️  发现 {len(orphans)} 个孤儿文件:")
                for o in orphans:
                    print(f"    - #{o['id']} {o['filename']} (status: {o['status']})")
            else:
                print(f"  ✅ 无孤儿文件")
            print(f"\n{'='*50}\n")

    finally:
        conn.close()

    return report


def search(
    filename: Optional[str] = None,
    tag: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    source_type: Optional[str] = None,
    keyword: Optional[str] = None,
    verbose: bool = True,
) -> list[dict]:
    """
    多维度搜索文件记录。

    参数:
        filename: 文件名模糊搜索。
        tag: 标签精确搜索。
        category: 分类精确搜索（使用标准化分类）。
        source: 来源过滤 ('incoming' | 'platform' | 'archive')。
        source_type: 来源类型过滤。
        keyword: 关键词搜索。
        verbose: 是否打印结果。

    返回:
        匹配的记录列表。
    """
    ensure_db()
    conn = get_db()
    results = []

    try:
        conditions = []
        params = []

        if filename:
            conditions.append("filename LIKE ?")
            params.append(f"%{filename}%")

        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")

        if category:
            conditions.append("category = ?")
            params.append(category)

        if source:
            if source in VALID_SOURCES:
                conditions.append("source = ?")
                params.append(source)
            else:
                print(f"[WARN] 无效 source: {source} (有效值: {', '.join(VALID_SOURCES)})",
                      file=sys.stderr)

        if source_type:
            if source_type in VALID_SOURCE_TYPES:
                conditions.append("source_type = ?")
                params.append(source_type)
            else:
                print(f"[WARN] 无效 source_type: {source_type} (有效值: {', '.join(VALID_SOURCE_TYPES)})",
                      file=sys.stderr)

        if keyword:
            conditions.append("(filename LIKE ? OR tags LIKE ? OR note LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)

        query = f"SELECT * FROM files{where_clause} ORDER BY imported_at DESC"
        cursor = conn.execute(query, params)

        for row in cursor.fetchall():
            results.append(dict(row))

        if verbose:
            print(f"\n[SEARCH] 条件: ", end="")
            parts = []
            if filename:
                parts.append(f"文件名~'{filename}'")
            if tag:
                parts.append(f"标签~'{tag}'")
            if category:
                parts.append(f"分类='{category}'")
            if source:
                parts.append(f"来源='{source}'")
            if source_type:
                parts.append(f"source_type='{source_type}'")
            if keyword:
                parts.append(f"关键词~'{keyword}'")
            print(" & ".join(parts) if parts else "无限制")
            print(f"共 {len(results)} 条结果\n")

            if results:
                print(f"  {'ID':<4} {'文件名':<30} {'分类':<14} {'来源':<10} {'状态':<10} {'SType':<12} {'创建时间':<18}")
                print(f"  {'-'*100}")
                for r in results:
                    print(f"  {r['id']:<4} {truncate_str(r['filename'], 28):<30} "
                          f"{truncate_str(r['category'] or '', 12):<14} "
                          f"{truncate_str(r['source'] or '', 8):<10} "
                          f"{truncate_str(r['status'] or '', 8):<10} "
                          f"{truncate_str(r['source_type'] or '', 10):<12} "
                          f"{r['created_at']:<18}")
                print()

    finally:
        conn.close()

    return results


def truncate_str(s: str, max_len: int) -> str:
    """截断字符串到指定长度。"""
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def update_record(
    original_path: str,
    current_path: Optional[str] = None,
    status: Optional[str] = None,
    category: Optional[str] = None,
    source_type: Optional[str] = None,
    tags: Optional[str] = None,
    note: Optional[str] = None,
    verbose: bool = True,
) -> bool:
    """
    更新文件记录的 current_path/status/category/source_type/tags/note。

    参数:
        original_path: 原始路径。
        current_path: 当前路径（随文件移动更新）。
        status: 状态。
        category: 分类（使用标准化分类）。
        source_type: 来源类型。
        tags: 逗号分隔标签。
        note: 备注。
        verbose: 输出详细信息。

    返回:
        是否更新成功。
    """
    ensure_db()
    conn = get_db()

    try:
        cursor = conn.execute(
            "SELECT id FROM files WHERE original_path = ?",
            (original_path,),
        )
        row = cursor.fetchone()
        if not row:
            print(f"[ERROR] 未找到记录: {original_path}", file=sys.stderr)
            return False

        if status and status not in VALID_STATUSES:
            print(f"[ERROR] 无效状态: {status} (有效值: {', '.join(VALID_STATUSES)})",
                  file=sys.stderr)
            return False

        if category and category not in VALID_CATEGORIES:
            print(f"[WARN] 非标准分类: {category} (建议使用标准分类)", file=sys.stderr)

        if source_type and source_type not in VALID_SOURCE_TYPES:
            print(f"[ERROR] 无效 source_type: {source_type} (有效值: {', '.join(VALID_SOURCE_TYPES)})",
                  file=sys.stderr)
            return False

        updates = []
        params = []

        if current_path is not None:
            updates.append("current_path = ?")
            params.append(current_path)

        if status is not None:
            updates.append("status = ?")
            params.append(status)

        if category is not None:
            updates.append("category = ?")
            params.append(category)

        if source_type is not None:
            updates.append("source_type = ?")
            params.append(source_type)

        if tags is not None:
            updates.append("tags = ?")
            params.append(tags)

        if note is not None:
            updates.append("note = ?")
            params.append(note)

        if not updates:
            if verbose:
                print("[SKIP] 无需更新（未指定任何字段）")
            return True

        params.append(original_path)
        conn.execute(
            f"UPDATE files SET {', '.join(updates)} WHERE original_path = ?",
            params,
        )
        conn.commit()

        if verbose:
            updated_fields = ", ".join(
                f"{f.split('=')[0].strip()}" for f in updates
            )
            print(f"[UPDATE] 已更新 #{row['id']}: {updated_fields}")

        return True

    finally:
        conn.close()


def show_status(verbose: bool = True) -> dict:
    """显示数据库概览。"""
    ensure_db()
    conn = get_db()
    stats = {}

    try:
        cursor = conn.execute("SELECT COUNT(*) as total FROM files")
        total = cursor.fetchone()["total"]
        stats["total"] = total
        if verbose:
            print(f"\n{'='*50}")
            print(f"  注册库状态概览")
            print(f"{'='*50}")
            print(f"  总记录数: {total}")
            print()

        print(f"  按来源分布:")
        print(f"  {'来源':<12} {'数量':>6}")
        print(f"  {'-'*20}")
        cursor = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM files GROUP BY source ORDER BY cnt DESC"
        )
        source_dist = {}
        for row in cursor.fetchall():
            s = row["source"] or "unknown"
            cnt = row["cnt"]
            source_dist[s] = cnt
            if verbose:
                print(f"  {s:<12} {cnt:>6}")
        stats["source_distribution"] = source_dist
        if verbose:
            print()

        print(f"  按状态分布 (标准化):")
        print(f"  {'状态':<14} {'数量':>6}")
        print(f"  {'-'*22}")
        cursor = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM files GROUP BY status ORDER BY cnt DESC"
        )
        status_dist = {}
        for row in cursor.fetchall():
            s = row["status"] or "unknown"
            cnt = row["cnt"]
            status_dist[s] = cnt
            if verbose:
                print(f"  {s:<14} {cnt:>6}")
        stats["status_distribution"] = status_dist
        if verbose:
            print()

        print(f"  按分类分布 (标准化):")
        print(f"  {'分类':<14} {'数量':>6}")
        print(f"  {'-'*22}")
        cursor = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM files GROUP BY category ORDER BY cnt DESC"
        )
        cat_dist = {}
        for row in cursor.fetchall():
            c = row["category"] or "unclassified"
            cnt = row["cnt"]
            cat_dist[c] = cnt
            if verbose:
                print(f"  {c:<14} {cnt:>6}")
        stats["category_distribution"] = cat_dist
        if verbose:
            print()

        print(f"  按 source_type 分布:")
        print(f"  {'Source Type':<14} {'数量':>6}")
        print(f"  {'-'*22}")
        cursor = conn.execute(
            "SELECT source_type, COUNT(*) as cnt FROM files GROUP BY source_type ORDER BY cnt DESC"
        )
        st_dist = {}
        for row in cursor.fetchall():
            st = row["source_type"] or "unknown"
            cnt = row["cnt"]
            st_dist[st] = cnt
            if verbose:
                print(f"  {st:<14} {cnt:>6}")
        stats["source_type_distribution"] = st_dist
        if verbose:
            print()

        seven_days_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM files WHERE imported_at >= ?",
            (seven_days_ago,),
        )
        recent = cursor.fetchone()["cnt"]
        stats["recent_7_days"] = recent
        if verbose:
            print(f"  最近7天新增: {recent}")

        print(f"\n  最近7天每日新增:")
        print(f"  {'日期':<14} {'数量':>6}")
        print(f"  {'-'*20}")
        cursor = conn.execute(
            """SELECT SUBSTR(imported_at, 1, 10) as day, COUNT(*) as cnt
               FROM files
               WHERE imported_at >= ?
               GROUP BY day
               ORDER BY day DESC""",
            (seven_days_ago,),
        )
        for row in cursor.fetchall():
            print(f"  {row['day']:<14} {row['cnt']:>6}")
        print(f"\n{'='*50}\n")

    finally:
        conn.close()

    return stats


def export_csv(output_path: Optional[str] = None, verbose: bool = True) -> str:
    """导出注册库全部记录到 CSV 文件。"""
    ensure_db()
    conn = get_db()

    if output_path is None:
        output_path = str(PROJECT_ROOT / "reports" / f"file_registry_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    try:
        cursor = conn.execute("SELECT * FROM files ORDER BY imported_at DESC")
        columns = [desc[0] for desc in cursor.description]

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", encoding="utf-8-sig") as f:
            f.write(",".join(columns) + "\n")
            for row in cursor.fetchall():
                values = []
                for col in columns:
                    val = str(row[col] or "")
                    if "," in val or '"' in val or "\n" in val:
                        val = '"' + val.replace('"', '""') + '"'
                    values.append(val)
                f.write(",".join(values) + "\n")

        if verbose:
            print(f"[CSV] 已导出: {out_path} ({out_path.stat().st_size} bytes)")

        return str(out_path)

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="file_lifecycle — 文件生命周期管理 v3 (标准化 category/status, current_path, checksum, source_type)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "使用示例:\n"
            "  python file_lifecycle.py init                   # 初始化数据库\n"
            "  python file_lifecycle.py init --force           # 重建数据库（DROP+CREATE）\n"
            "  python file_lifecycle.py register-incoming      # 登记当天 incoming 文件\n"
            "  python file_lifecycle.py archive-scan           # 扫描存档仓库（标准化分类）\n"
            "  python file_lifecycle.py daily-maintenance      # 每日维护（自动摘要提取）\n"
            "  python file_lifecycle.py scan-registry          # 扫描 registry 生成统计\n"
            "  python file_lifecycle.py search --source-type migrated\n"
            "  python file_lifecycle.py update --path ... --status production\n"
            "  python file_lifecycle.py status                 # 数据库概览\n"
            "  python file_lifecycle.py export                 # 导出 CSV\n"
        ),
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # init
    parser_init = subparsers.add_parser("init", help="初始化数据库（创建表结构）")
    parser_init.add_argument(
        "--force", "-f", action="store_true",
        help="强制重建（DROP + CREATE），用于结构变更后重建",
    )

    # register-incoming
    parser_register = subparsers.add_parser("register-incoming",
        help="登记 incoming 文件到数据库 (source='incoming', source_type='unknown')")
    parser_register.add_argument(
        "--date", "-d", type=str, default=None,
        help="日期目录 (YYYYMMDD)，默认当天",
    )
    parser_register.add_argument(
        "--all-dates", "-a", action="store_true",
        help="扫描所有日期目录",
    )
    parser_register.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式",
    )
    parser_register.add_argument(
        "--dry-run", "-n", action="store_true",
        help="仅模拟，不实际写入",
    )

    # archive-scan
    parser_archive = subparsers.add_parser("archive-scan",
        help="扫描存档仓库登记到 registry （标准化分类，source_type='migrated'）")
    parser_archive.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式",
    )
    parser_archive.add_argument(
        "--dry-run", "-n", action="store_true",
        help="仅模拟，不实际写入",
    )

    # daily-maintenance
    parser_daily = subparsers.add_parser("daily-maintenance",
        help="每日维护：扫描 incoming 并自动生成缺失 meta（含自动摘要提取）")
    parser_daily.add_argument(
        "--date", "-d", type=str, default=None,
        help="日期目录 (YYYYMMDD)，默认所有日期",
    )
    parser_daily.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式",
    )
    parser_daily.add_argument(
        "--dry-run", "-n", action="store_true",
        help="仅模拟，不实际写入",
    )

    # scan-registry
    parser_scan = subparsers.add_parser("scan-registry", help="扫描 registry 生成统计报告")
    parser_scan.add_argument(
        "--quiet", "-q", action="store_true",
        help="静默模式，返回 JSON",
    )

    # search
    parser_search = subparsers.add_parser("search", help="多维度搜索文件记录")
    parser_search.add_argument("--filename", "-f", type=str, default=None, help="文件名模糊搜索")
    parser_search.add_argument("--tag", "-t", type=str, default=None, help="标签搜索")
    parser_search.add_argument("--category", "-c", type=str, default=None, help="分类精确搜索")
    parser_search.add_argument("--source", "-s", type=str, default=None,
                               choices=VALID_SOURCES, help="来源过滤")
    parser_search.add_argument("--source-type", "-st", type=str, default=None,
                               choices=VALID_SOURCE_TYPES, help="来源类型过滤")
    parser_search.add_argument("--keyword", "-k", type=str, default=None, help="关键词搜索")
    parser_search.add_argument("--json", "-j", action="store_true", help="JSON 格式输出")

    # update
    parser_update = subparsers.add_parser("update", help="更新文件记录")
    parser_update.add_argument("--path", "-p", type=str, required=True, help="原始路径")
    parser_update.add_argument("--current-path", "-cp", type=str, default=None, help="当前路径")
    parser_update.add_argument("--status", "-s", type=str, default=None,
                               choices=VALID_STATUSES, help="新状态")
    parser_update.add_argument("--category", "-c", type=str, default=None,
                               choices=VALID_CATEGORIES, help="新分类")
    parser_update.add_argument("--source-type", "-st", type=str, default=None,
                               choices=VALID_SOURCE_TYPES, help="来源类型")
    parser_update.add_argument("--tags", "-t", type=str, default=None, help="新标签 (逗号分隔)")
    parser_update.add_argument("--note", "-n", type=str, default=None, help="新备注")

    # status
    subparsers.add_parser("status", help="数据库状态概览")

    # export
    parser_export = subparsers.add_parser("export", help="导出注册库为 CSV")
    parser_export.add_argument("--output", "-o", type=str, default=None, help="输出路径")

    # batch register
    parser_batch = subparsers.add_parser("batch-register", help="批量登记所有日期目录")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    verbose = not getattr(args, "quiet", False)

    if args.command == "init":
        if args.force:
            rebuild_db()
        else:
            ensure_db()
            print(f"[OK] 数据库已初始化: {DB_PATH}")

    elif args.command == "register-incoming":
        if args.all_dates:
            count = register_incoming(date_str=None, verbose=verbose, dry_run=args.dry_run)
        else:
            date_str = args.date
            count = register_incoming(date_str=date_str, verbose=verbose, dry_run=args.dry_run)
        if verbose:
            print(f"[DONE] register-incoming: {count} 条新记录")

    elif args.command == "archive-scan":
        count = archive_scan(verbose=verbose, dry_run=args.dry_run)
        if verbose:
            print(f"[DONE] archive-scan: {count} 条新记录")

    elif args.command == "daily-maintenance":
        report = daily_maintenance(
            verbose=verbose,
            dry_run=args.dry_run,
            date_str=args.date,
        )
        if not verbose:
            print(json.dumps(report, ensure_ascii=False, indent=2))

    elif args.command == "batch-register":
        count = register_incoming(date_str=None, verbose=verbose)
        if verbose:
            print(f"[DONE] batch-register: {count} 条新记录")

    elif args.command == "scan-registry":
        report = scan_registry(verbose=verbose)
        if not verbose:
            print(json.dumps(report, ensure_ascii=False, indent=2))

    elif args.command == "search":
        results = search(
            filename=args.filename,
            tag=args.tag,
            category=args.category,
            source=args.source,
            source_type=getattr(args, "source_type", None),
            keyword=args.keyword,
            verbose=not args.json,
        )
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))

    elif args.command == "update":
        success = update_record(
            original_path=args.path,
            current_path=args.current_path,
            status=args.status,
            category=args.category,
            source_type=args.source_type,
            tags=args.tags,
            note=args.note,
            verbose=verbose,
        )
        sys.exit(0 if success else 1)

    elif args.command == "status":
        show_status(verbose=verbose)

    elif args.command == "export":
        export_csv(output_path=args.output, verbose=verbose)


if __name__ == "__main__":
    main()

