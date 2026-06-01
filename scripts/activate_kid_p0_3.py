"""Activate KID-P0-3-001"""
import json

path = r"C:\Users\17699\mozhi_platform\knowledge_entries\draft\KID-P0-3-001_adj_factor_formula_fix.json"
kid = json.load(open(path, encoding="utf-8"))
kid["status"] = "active"
kid["signatories"]["moxuan"] = "2026-05-28T09:47:00+08:00"
kid["signatories"]["xuanzhi"] = "2026-05-28T09:53:00+08:00"
kid["signatories"]["owner"] = "2026-05-28T09:56:00+08:00"
json.dump(kid, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"KID activated: {kid['knowledge_id']}")
print(f"Status: {kid['status']}")
print(f"Signatories: {len(kid['signatories'])}")
for k, v in kid["signatories"].items():
    print(f"  {k}: {v}")
