import json, os
from datetime import datetime, timezone, timedelta

tz = timezone(timedelta(hours=8))
now = datetime.now(tz).strftime("%Y-%m-%dT%H:%M:%S+08:00")

sub_tasks = [
    ("P1_001a", "涨跌停常量和边界计算函数", 15, []),
    ("P1_001b", "check_limit_trade 预检实现", 15, ["P1_001a"]),
    ("P1_001c", "引擎集成（预检插入）", 10, ["P1_001b"]),
    ("P1_002a", "流动性分档逻辑", 15, []),
    ("P1_002b", "DynamicSlippage 模型实现", 15, ["P1_002a"]),
    ("P1_002c", "OrderExecutor 集成", 15, ["P1_002b"]),
    ("P1_003a", "容量控制约束函数", 15, []),
    ("P1_003b", "Engine/Executor 容量集成", 15, ["P1_003a", "P1_001c"]),
    ("P1_004a", "集合竞价逻辑", 15, []),
    ("P1_004b", "Bar 增强 + 引擎开盘执行", 15, ["P1_004a", "P1_002c"]),
]

# BFS topological sort by levels
levels = {}
for sid, _, _, deps in sub_tasks:
    if not deps:
        levels[sid] = 0
    else:
        levels[sid] = max(levels.get(d, -1) for d in deps) + 1

ordered = sorted(sub_tasks, key=lambda s: (levels[s[0]], s[0]))
print("Topological order:")
for sid, desc, est, deps in ordered:
    print(f"  {sid}: {desc} ({est}min) lv={levels[sid]}")

stages = []

# Generate coding + self-check stages in topological order
for sid, desc, est_min, deps in ordered:
    st_id = f"stage_1_{sid.lower()}"
    deps_stage = [f"stage_1.5_{d.lower()}" for d in deps]
    sc_id = f"stage_1.5_{sid.lower()}"

    # Coding stage
    stages.append({
        "id": st_id,
        "type": "coding",
        "sub_task_id": sid,
        "description": desc,
        "estimated_min": est_min,
        "timeout_min": max(est_min * 2, 30),
        "deps": deps_stage,
        "dynamic_next": {
            "SUCCESS": sc_id,
            "FAILURE": st_id,
            "REJECT": st_id,
            "default": None
        },
        "state_file": f"signals/tasks/p1_{sid.lower()}.json",
        "done_file": f"signals/tasks/p1_{sid.lower()}.done",
        "agent": "moheng",
        "affected_files": [],
        "acceptance_criteria": desc
    })

    # Self-check stage (placeholder SUCCESS target)
    stages.append({
        "id": sc_id,
        "type": "self_check",
        "sub_task_id": sid,
        "description": f"{sid} 自检",
        "estimated_min": 5,
        "timeout_min": 15,
        "deps": [st_id],
        "dynamic_next": {
            "SUCCESS": None,  # wired below
            "WARN": st_id,
            "FAILURE": st_id,
            "default": None
        },
        "state_file": f"signals/tasks/p1_selfcheck_{sid.lower()}.json",
        "done_file": f"signals/tasks/p1_selfcheck_{sid.lower()}.done",
        "agent": "moheng",
        "affected_files": [],
        "acceptance_criteria": f"{sid} 自检通过"
    })

# Wire up self-check SUCCESS targets
sc_stages = [s for s in stages if s["type"] == "self_check"]
for i, sc in enumerate(sc_stages):
    if i < len(sc_stages) - 1:
        sc["dynamic_next"]["SUCCESS"] = sc_stages[i + 1]["id"]
    else:
        sc["dynamic_next"]["SUCCESS"] = "stage_2"

# Stage 2 - Code Review (墨萱)
stages.append({
    "id": "stage_2",
    "type": "review",
    "description": "墨萱代码审查（所有 sub_task 合流版本）",
    "estimated_min": 15,
    "timeout_min": 30,
    "deps": [s["id"] for s in stages if s["type"] == "self_check"],
    "dynamic_next": {
        "SUCCESS": "stage_3",
        "FAILURE": None,
        "REJECT": None,
        "default": None
    },
    "state_file": "signals/tasks/p1_stage_2.json",
    "done_file": "signals/tasks/p1_stage_2.done",
    "agent": "moxuan",
    "affected_files": [],
    "acceptance_criteria": "所有 sub_task 代码审查通过"
})

# Stage 3 - Architecture Review (玄知)
stages.append({
    "id": "stage_3",
    "type": "architecture",
    "description": "玄知架构把关",
    "estimated_min": 15,
    "timeout_min": 30,
    "deps": ["stage_2"],
    "dynamic_next": {
        "SUCCESS": "stage_4",
        "CONDITIONAL_PASS": "stage_4",
        "REJECT": "stage_2",
        "default": None
    },
    "state_file": "signals/tasks/p1_stage_3.json",
    "done_file": "signals/tasks/p1_stage_3.done",
    "agent": "xuanzhi",
    "affected_files": [],
    "acceptance_criteria": "架构和数据流一致性验证通过"
})

# Stage 4 - Knowledge (墨涵)
stages.append({
    "id": "stage_4",
    "type": "knowledge",
    "description": "墨涵知识归档 + KID 创建",
    "estimated_min": 5,
    "timeout_min": 15,
    "deps": ["stage_3"],
    "dynamic_next": {
        "SUCCESS": "stage_5",
        "FAILURE": "stage_2",
        "default": None
    },
    "state_file": "signals/tasks/p1_stage_4.json",
    "done_file": "signals/tasks/p1_stage_4.done",
    "agent": "mohan",
    "affected_files": [],
    "acceptance_criteria": "知识条目创建并会签"
})

# Stage 5 - Owner signoff
stages.append({
    "id": "stage_5",
    "type": "signoff",
    "description": "Owner 签署确认",
    "estimated_min": 5,
    "timeout_min": 30,
    "deps": ["stage_4"],
    "dynamic_next": {
        "SUCCESS": None,
        "default": None
    },
    "state_file": "signals/tasks/p1_stage_5.json",
    "done_file": "signals/tasks/p1_stage_5.done",
    "agent": "owner",
    "affected_files": [],
    "acceptance_criteria": "业务方向确认"
})

pipeline = {
    "meta": {
        "title": "P1 编码流水线（涨跌停/滑点/容量/开盘价）",
        "version": "1.0",
        "generated_by": "mohan",
        "generated_at": now,
        "parent_task": "P1",
        "total_estimated_min": 145 + 50,
        "split_final_file": "schedules/split_final_p1.json",
        "status": "draft"
    },
    "stages": stages
}

output_path = r"C:\Users\17699\mozhi_platform\schedules\coding_pipeline_p1.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(pipeline, f, indent=2, ensure_ascii=False)

n_coding = len([s for s in stages if s["type"] == "coding"])
n_sc = len([s for s in stages if s["type"] == "self_check"])
n_other = len(stages) - n_coding - n_sc

print(f"Written: {output_path}")
print(f"Total stages: {len(stages)} (coding={n_coding}, self_check={n_sc}, other={n_other})")
