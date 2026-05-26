# research_failures/records/

> **注意**: 本目录用于存放手动的详细研究失败复盘记录（YAML/JSON格式）。
> 
> 系统自动写入的 Q9b 记录通过 `ResearchFailuresRegistry` 类操作，
> 存储在 `research_failures/research_failures.db` SQLite 数据库。

## 使用说明

1. **自动方式**（推荐）：使用 `ResearchFailuresRegistry` 进行 CRUD 操作
2. **手动方式**：直接在此目录下创建 `YYYY-MM-DD_strategy-name_desc.yaml` 文件
 
### 手动记录格式

```yaml
failure_id: "UUID or 'auto'"
strategy_name: "grid_601857"
researcher: "moheng" 
failure_type_verbose: "TEMPORAL_DECAY / STATISTICAL_INSUFFICIENCY / REGIME_DEPENDENT / ..."
root_cause: "选股因子在趋势向上时有效，但在震荡市中方向相反"
discovery_date: "2026-05-19"
data_source_version: "wind_v2.3.0"
notes: |
  详细复盘笔记...
cross_ref_q9a: null  # 或 Q9a failure_id
```
