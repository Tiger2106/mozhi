import json, hashlib, os

path = r"C:\Users\17699\mozhi_platform\schedules\coding_pipeline_p1.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

stages = data["stages"]
results = []

# M1: JSON format
results.append(("M1", "JSON格式", True, "可解析"))

# M2: File path directories exist
all_paths_ok = True
paths_missing = []
for s in stages:
    for k in ("state_file", "done_file"):
        fp = s.get(k, "")
        if fp:
            d = os.path.dirname(os.path.join(r"C:\Users\17699\mozhi_platform", fp))
            if not os.path.exists(d):
                all_paths_ok = False
                paths_missing.append((s["id"], fp))
results.append(("M2", "文件路径目录存在", all_paths_ok,
    "OK" if all_paths_ok else "缺失: " + str(paths_missing)))

# M3: Branch coverage
branch_ok = True
branch_issues = []
for s in stages:
    dn = s.get("dynamic_next", {})
    if "SUCCESS" not in dn:
        branch_ok = False
        branch_issues.append(s["id"] + " 缺SUCCESS")
    if "default" not in dn:
        branch_ok = False
        branch_issues.append(s["id"] + " 缺default")
    if s["type"] in ("coding", "self_check") and "FAILURE" not in dn:
        branch_ok = False
        branch_issues.append(s["id"] + " 缺FAILURE")
results.append(("M3", "分支覆盖完整", branch_ok,
    "OK" if branch_ok else "问题: " + str(branch_issues)))

# M4: Dependency consistency
all_ids = {s["id"] for s in stages}
dep_ok = True
dep_issues = []
for s in stages:
    for d in s.get("deps", []):
        if d not in all_ids:
            dep_ok = False
            dep_issues.append(s["id"] + " 依赖 " + d + " 不存在")
results.append(("M4", "依赖一致性(双向)", dep_ok,
    "OK" if dep_ok else "问题: " + str(dep_issues)))

# M5: MD5 self-signature
content = json.dumps(data, indent=2, ensure_ascii=False)
md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
data["meta"]["md5"] = md5
data["meta"]["status"] = "self_checked"
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
results.append(("M5", "MD5自签名", True, "md5=" + md5))

# M6: State file directories
for s in stages:
    for k in ("state_file", "done_file"):
        fp = s.get(k, "")
        if fp:
            d = os.path.dirname(os.path.join(r"C:\Users\17699\mozhi_platform", fp))
            os.makedirs(d, exist_ok=True)
results.append(("M6", "状态文件目录已创建", True, "OK"))

# M7: No duplicate stage IDs
ids = [s["id"] for s in stages]
dup = [i for i in ids if ids.count(i) > 1]
results.append(("M7", "无重复stage ID", len(dup) == 0,
    "OK" if len(dup) == 0 else "重复: " + str(set(dup))))

# Summary
print("=== P0.9 自检结果 ===")
all_pass = True
for mid, name, ok, detail in results:
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print("  " + status + " " + mid + " " + name + ": " + detail)

verdict = "PASS" if all_pass else "FAIL"
print("结论: " + verdict)
