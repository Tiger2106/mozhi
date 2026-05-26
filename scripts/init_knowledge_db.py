#!/usr/bin/env python3
"""建表脚本：创建或重建 knowledge.db 及其所有表结构。

用法:
    python scripts/init_knowledge_db.py           # 默认路径 data/knowledge.db
    python scripts/init_knowledge_db.py --db-path /path/to/knowledge.db
    python scripts/init_knowledge_db.py --force   # 备份后重建（不保留原有数据）
"""

import argparse
import sys
import os
from pathlib import Path

# 确保能从项目根运行
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.pipeline.knowledge_db import KnowledgeDB


def main():
    parser = argparse.ArgumentParser(
        description="创建或重建 knowledge.db 及其所有表结构"
    )
    parser.add_argument("--db-path", default=None,
                        help="数据库文件路径，默认 data/knowledge.db")
    parser.add_argument("--force", action="store_true",
                        help="备份后重建（不保留原有数据）")
    args = parser.parse_args()

    kdb = KnowledgeDB(db_path=args.db_path) if args.db_path else KnowledgeDB()

    if args.force and os.path.exists(kdb.db_path):
        # 先备份
        backup_path = kdb.backup(backup_dir=os.path.join(
            os.path.dirname(kdb.db_path), "db"
        ))
        print(f"已备份旧数据库到: {backup_path}")
        os.remove(kdb.db_path)
        print(f"已删除旧数据库: {kdb.db_path}")

    # 确保父目录存在（边缘场景：data/ 等目录缺失）
    Path(kdb.db_path).parent.mkdir(parents=True, exist_ok=True)

    kdb.initialize()
    print(f"知识库已初始化: {kdb.db_path}")
    kdb.close()


if __name__ == "__main__":
    main()
