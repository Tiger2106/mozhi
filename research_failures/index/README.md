# research_failures/index/

索引文件用于快速查找研究失败记录。当前支持两种索引方式：

1. **by_failure_type.json** — 按失败类型索引
2. **by_strategy.json** — 按策略名称索引
3. **by_researcher.json** — 按研究员索引

索引文件由 `ResearchFailuresRegistry.build_index()` 自动维护，
也可通过 `tools/rebuild_index.py` 手动重建。
