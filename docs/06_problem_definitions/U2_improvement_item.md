---
author: 墨涵
created_time: 2026-05-31T11:54+08:00
type: tracking_item_v1.0
parent: T21_FULLRUN_20260530
status: PENDING
priority: P2
---

# U2 — 精确写入区分（独立改进项）

## 来源
T21_FULLRUN_20260530 问题定义中的U2未确认项，T21关闭后转为独立改进项。

## 问题描述
管线多次运行时，同一截面数据被写入多条记录，无法精确区分哪些数据来自哪次运行（第1次OOM中断后写入的222截面 vs 第2次续跑的428截面）。

## 已有产出
- 解决方案方案B2：`docs/06_problem_definitions/plan_solve_U2_20260531.md`（新增run_id列+重跑）
- 试验方案v2.1：`docs/06_problem_definitions/experiment_plan_U2_repro_v2.1.md`（含Phase 0/1/2/3，已通过墨萱+玄知评审）
- 墨萱评审：✅ PASS（v2.1）
- 玄知评审：✅ PASS WITH CONDITIONS（3项先决条件：taskkill预验证、Defender排除+Windows Update检查、管线启动打印PID）

## 待执行条件
1. Owner排期后启动
2. Phase 0代码改动（run_id列+唯一索引更新+实例方法_build_null_record）
3. Phase 1 small-scale验证（需8项PASS标准）
4. Phase 2近5年重跑（需6项PASS标准）
5. Phase 3全量重跑（可选）

## 标签
- T21_CLOSED
- improvement
- observability
