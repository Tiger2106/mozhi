"""Register BitableSync files into file_registry."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from src.utils.file_lifecycle import get_db, compute_checksum, now_str, ensure_db

FILES = [
    ("credentials.json", "config/credentials.json", "backtest", "production", "manual",
     "credentials,feishu,bitable,config",
     "feishu app credentials (mochen cli_a94fe82768381cc5), secret from FEISHU_MOCHEN_APP_SECRET"),
    ("bitable_sync.py", "src/backtest/engine/bitable_sync.py", "backtest", "production", "ai_deepseek",
     "bitable,sync,real-api,credentials",
     "BitableSync v2: real Feishu API (_fetch_token/_create_record/_update_record), _load_credentials, FIELD_MAP realigned"),
    ("test_bitable_sync.py", "src/backtest/tests/test_bitable_sync.py", "backtest", "production", "ai_deepseek",
     "tests,bitable,real-api,28-tests",
     "28 tests: simulate 18 + real 6 + bridge/degrade 4, adapted for new field names and credential auto-load"),
]

def main():
    ensure_db()
    db = get_db()
    imported_at = now_str()
    count = 0

    for filename, relpath, category, status, stype, tags, note in FILES:
        full_path = os.path.join(os.path.dirname(__file__), relpath)
        checksum = compute_checksum(full_path) if os.path.exists(full_path) else ""

        existing = db.execute("SELECT id FROM files WHERE original_path = ?", (relpath,)).fetchone()
        if existing:
            print(f"[SKIP] {filename} (id={existing[0]})")
            continue

        db.execute(
            "INSERT INTO files (filename,original_path,current_path,category,source,status,source_type,checksum,tags,note,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (filename, relpath, relpath, category, "mozhi_platform", status, stype, checksum, tags, note, imported_at)
        )
        print(f"[REGISTER] {filename}")
        count += 1

    db.commit()
    print(f"\nDone. {count} registered.")

if __name__ == "__main__":
    main()
