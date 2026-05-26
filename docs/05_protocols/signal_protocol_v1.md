# Signal Protocol v1

**领域**: 研究系统（Research） ↔ 交易系统（Trading）信号交换协议
**版本**: 1.0
**状态**: ✅ 批准
**批准依据**: ADR-004 / Owner 2026-05-20 裁决
**作者**: 墨衡
**创建日期**: 2026-05-20
**总篇数**: 6

---

## 目录

1. [Schema（信号结构）](#1-schema信号结构)
    - 1.1 Core 字段定义
    - 1.2 Extension 字段定义
    - 1.3 Direction ↔ 信号强度/权重对应
    - 1.4 序列化格式
    - 1.5 序列化/反序列化验证规则
2. [Version（版本管理）](#2-version版本管理)
    - 2.1 版本号规则
    - 2.2 向后兼容策略
    - 2.3 字段变更流程
3. [Lifecycle（信号生命周期）](#3-lifecycle信号生命周期)
    - 3.1 生命周期状态机
    - 3.2 各阶段详细说明
    - 3.3 超时与过期策略
4. [Compatibility（兼容性保证）](#4-compatibility兼容性保证)
    - 4.1 版本兼容矩阵（1.0 vs 1.1）
    - 4.2 字段兼容规则
    - 4.3 降级策略
    - 4.4 兼容性测试用例
5. [附录](#5-附录)
    - A. Python 数据类参考实现
    - B. JSON Schema 定义
    - C. 协议变更模板（ADR 提案格式）

---

## 1. Schema（信号结构）

### 1.1 Core 字段定义

Core 字段一旦冻结，协议版本升级前不允许修改。任何修改 Core 的行为必须触发协议版本主号递增（见 §2）。

| 字段 | 类型 | 取值范围 / 约束 | 必填 | 说明 |
|:-----|:-----|:----------------|:----:|:-----|
| `signal_id` | `str` | UUID v4 格式 `xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx` | ✅ | 全局唯一信号标识符 |
| `symbol` | `str` | A股：6位数字代码（如 `"601857"`） | ✅ | 标的证券代码，不含市场前缀 |
| `direction` | `Literal["BUY", "SELL", "HOLD"]` | 仅限 `BUY` / `SELL` / `HOLD` 三值 | ✅ | 交易方向，见 §1.3 强度映射 |
| `confidence` | `float` | `0.0 ≤ confidence ≤ 1.0`，精度 4 位小数 | ✅ | 信号置信度，越高越确定 |
| `horizon` | `str` | 枚举：`"short"` / `"mid"` / `"long"` | ✅ | 信号有效时间跨度 |
| `signal_type` | `str` | 枚举：`"trend"` / `"reversal"` / `"grid"` | ✅ | 信号类型 |
| `timestamp` | `datetime` | ISO 8601 格式，时区 `+08:00`，精度秒级 | ✅ | 信号生成时刻 |
| `protocol_version` | `str` | SemVer 格式 `"MAJOR.MINOR"`，当前 `"1.0"` | ✅ | 协议版本 |

#### 字段约束细则

**signal_id**:
- 必须使用 UUID v4，由 Research 端在生成信号时分配
- 禁止重用：同一颗 UUID 在协议生命周期内不得出现两次
- 格式正则：`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`

**symbol**:
- A股：6位数字字符串（如 `"000001"`、`"601857"`），不含 `.SZ` / `.SH` 后缀
- 跨市场扩展通过 `extras.market` 字段承载，不在 `symbol` 字段做拼接

**confidence**:
- 语义映射：`0.0` = 完全不确定，`1.0` = 绝对确信
- 序列化保留 4 位小数，反序列化时四舍五入到 4 位
- Consumer 端不得对 `confidence` 做任何归一化/缩放处理

**horizon**:
- `"short"`: 日内 ~ 3 个交易日
- `"mid"`: 3 个交易日 ~ 30 个交易日
- `"long"`: 30 个交易日以上
- Research 端必须给出明确 horizon，不得为空

**signal_type**:
- `"trend"`: 趋势跟踪信号（动量、均线类）
- `"reversal"`: 反转信号（超买超卖、均值回归类）
- `"grid"`: 网格/震荡信号（区间反弹类）
- 自定义类型需通过 `extras` 扩展，不得修改 `signal_type` 枚举

**timestamp**:
- 必须包含时区偏移，不得使用 naive datetime
- 精度到秒（`YYYY-MM-DDTHH:mm:ss+08:00`），微秒级精度不在此协议规范内
- 由信号发生器赋值，Consumer 不得修改

**protocol_version**:
- 格式 `MAJOR.MINOR`，无 PATCH 段
- 当前 `"1.0"`
- Consumer 根据此字段选择解析策略（见 §4.3 降级策略）

### 1.2 Extension 字段定义

| 字段 | 类型 | 必填 | 说明 |
|:-----|:-----|:----:|:-----|
| `extras` | `dict` | ❌ | 可扩展字典，v1不限制结构 |

#### extras 使用规范

1. **命名空间约定**: 使用 `.` 分隔的前缀防止键冲突
   - `ml.feature_importances`: ML 模型因子权重
   - `factor.pe_ratio`: 解释因子值
   - `market.us`: 跨市场信号扩展
   - `analyst.notes`: 研究员注释

2. **类型约束**: 值必须为 JSON 可序列化的基本类型（`str` / `number` / `bool` / `list` / `dict` / `null`）

3. **禁止行为**:
   - ❌ 不得将 Core 字段的语义冗余到 extras（如 `extras.symbol`）
   - ❌ 不得在 extras 中声明 Core 字段的"替代版本"
   - ❌ extras 的 key 长度超过 128 字符

4. **v1 禁止域（红线机制）**: 以下 4 类数据绝对禁止写入 extras，违反即拒绝/告警（见 V-13）
   - 🔴 **Core 替补声明**: 任何意图替代 Core 字段的键（如 `extras.custom_direction`）— 理由：Core 字段是协议契约，不可在 extras 中设"后门"
   - 🔴 **二进制大数据**: base64 编码的模型权重、策略配置快照等非文本大对象 — 理由：Signal 不是存储系统，大对象应走知识库
   - 🔴 **敏感信息**: 交易员ID、账户号、API 密钥、客户信息 — 理由：Signal 是内部公共交换格式，不应携带认证信息
   - 🔴 **循环引用**: 信号ID指向自身、依赖链数据 — 理由：反序列化时无法建立引用关系，破坏确定性

   **6类例外（经三问规则自审查后可写入）**:
   - ✅ `ml.trial_*`: 新因子试运行（非正式因子字段，临时承载评估）
   - ✅ `debug.*`: 短期调试日志（上限 3 个 key，上线前必须清理）
   - ✅ `bridge.*`: 跨协议桥接数据（与其他系统交互时承载适配数据）
   - ✅ `compliance.*`: 合规/风控标注（需写明审批人）
   - ✅ `trace.*`: 链路追踪信息（trace_id、span_id 等分布式追踪数据）
   - ✅ `strategy.*`: 策略元数据（策略版本号、参数快照、run_id）

   **三问规则（写入任何 extras 前自问）**:
   1. ❓ 这个数据是否**本应属于 Core 字段**？
   2. ❓ 这个数据是否**应存储在 knowledge.db 而非信号中**？
   3. ❓ **如果我离职，下一个人能读懂**这个 extras 的用途吗？

   若任一答案为"是"，则不应写入 extras。

5. **v1 预留键（不强制，仅供规范参考）**:
   ```
   ml.*            → ML 模型相关
   factor.*        → 因子解释
   market.*        → 多市场扩展
   risk.*          → 风险标注
   analyst.*       → 人工注释
   ```

### 1.3 Direction ↔ 信号强度 / 权重对应

`direction` 字段的值受 `confidence` 约束，不能独立于置信度解读：

| direction | confidence 范围 | 语义强度 | 仓位权重建议 | 说明 |
|:---------:|:--------------:|:---------:|:-----------:|:-----|
| **BUY** | 0.8 ~ 1.0 | 强买入 | ≥ 0.6 | 高确信买入信号 |
| **BUY** | 0.5 ~ 0.8 | 弱买入 | 0.3 ~ 0.6 | 温和看多 |
| **BUY** | 0.0 ~ 0.5 | 试探性买入 | ≤ 0.3 | 低确信，仅供观察 |
| **SELL** | 0.8 ~ 1.0 | 强卖出 | ≥ 0.6 | 高确信卖出信号 |
| **SELL** | 0.5 ~ 0.8 | 弱卖出 | 0.3 ~ 0.6 | 温和看空 |
| **SELL** | 0.0 ~ 0.5 | 试探性卖出 | ≤ 0.3 | 低确信，仅供观察 |
| **HOLD** | 0.5 ~ 1.0 | 强烈建议持仓 | N/A | 方向明确为"不操作" |
| **HOLD** | 0.0 ~ 0.5 | 建议观望 | N/A | 方向不明确 |

**核心规则**: `direction + confidence` 联合解码，两者缺一不可。

- `BUY` + `confidence: 0.3` ≠ 买入指令，仅表示"倾向买入但很不确定"
- `HOLD` + `confidence: 0.9` = "强烈建议不操作"
- Consumer 端应使用 `direction * confidence` 联合权重来映射订单类型和仓位比例

### 1.4 序列化格式

#### 1.4.1 JSON（默认日志格式）

```json
{
  "signal_id": "550e8400-e29b-41d4-a716-446655440000",
  "symbol": "601857",
  "direction": "BUY",
  "confidence": 0.8250,
  "horizon": "short",
  "signal_type": "trend",
  "timestamp": "2026-05-20T10:30:00+08:00",
  "protocol_version": "1.0",
  "extras": {
    "factor.pe_ratio": 8.5,
    "ml.feature_importances": {"momentum_5d": 0.42, "volume_ratio": 0.33}
  }
}
```

**JSON 规范**:
- 编码: UTF-8 (without BOM)
- 缩进: 2 空格（开发环境）/ 无缩进（生产日志）
- 空 `extras`: 在文件写入时必须显式保留 `"extras": {}`，禁止省略
- 文件名模式: `signal_{signal_id}.json` 或批量文件 `signals_{batch_id}_{timestamp}.jsonl`
- 文件行格式: JSON Lines (`.jsonl`) —— 每行一个独立 JSON 对象，适合批量消费

#### 1.4.2 Parquet（批量分析格式）

**适用场景**: 日终批量分析、回测数据加载、历史信号归档

**Schema 映射**:

| JSON 字段 | Parquet 类型 | 备注 |
|:----------|:-------------|:-----|
| signal_id | `STRING` | |
| symbol | `STRING` | |
| direction | `STRING` | 枚举 `BUY/SELL/HOLD` |
| confidence | `DOUBLE` | |
| horizon | `STRING` | 枚举 `short/mid/long` |
| signal_type | `STRING` | 枚举 `trend/reversal/grid` |
| timestamp | `TIMESTAMP_MILLIS` | 本地时区（+08:00） |
| protocol_version | `STRING` | |
| extras | `STRUCT` 或 `STRING(JSON)` | v1 定为 `STRING(JSON)` 以保持灵活性 |

**规范**:
- 文件名: `signals_{date}_{batch_seq}.parquet`
- extras 在 Parquet 中序列化为 JSON 字符串存入 `STRING` 字段
- Compression: `snappy`（默认）/ `zstd`（归档）

### 1.5 序列化 / 反序列化验证规则

#### 验证器行为

| 规则编号 | 检查项 | 验证逻辑 | 失败行为 |
|:--------:|:-------|:---------|:---------|
| V-01 | `signal_id` 格式 | 正则 `^[0-9a-f\-]+$` + UUID v4 校验 | **拒绝**，抛出 `SchemaValidationError` |
| V-02 | `symbol` 完整性 | 非空、长度 ≤ 10 字符 | **拒绝** |
| V-03 | `direction` 合法性 | 值在 `["BUY", "SELL", "HOLD"]` 内 | **拒绝** |
| V-04 | `confidence` 范围 | `0.0 ≤ value ≤ 1.0` | **拒绝** |
| V-05 | `horizon` 合法性 | 值在 `["short", "mid", "long"]` 内 | **拒绝** |
| V-06 | `signal_type` 合法性 | 值在 `["trend", "reversal", "grid"]` 内 | **拒绝** |
| V-07 | `timestamp` 格式 | ISO 8601 + 时区偏移 | **拒绝** |
| V-08 | `protocol_version` 格式 | SemVer `MAJOR.MINOR` | **拒绝** |
| V-09 | 必需字段完备性 | 8个 Core 字段全部存在 | **拒绝** |
| V-10 | 未知字段处理 | 非 Core 字段写入 `extras` 或 `extras` 内 | Consumer 端 **降级跳过**（见 §4.3） |
| V-11 | UUID 唯一性校验 | 检查重复 signal_id（Log 模式下） | **警告+跳过**（非阻断） |
| V-12 | `extras` 类型 | 值必须为 `dict` | 空 `extras` → 提升为 `{}` |
| V-13 | `extras` 禁止域检查 | 宽松模式: 检查 4 类红线（Core替补/Binary大对象/敏感信息/循环引用），匹配则警告+记录 | Consumer 端 **警告+记录**（宽松模式）/ **拒绝**（严格模式） |
|      |                     | 严格模式: 匹配红线则拒绝；检查三问规则（本应属Core/应归knowledge.db/后人能读懂？），匹配建议不作拒绝 | |

#### 序列化器伪代码

```
def serialize(signal: Signal, format: str = "json") -> str/bytes:
    validate(signal)              # 运行 V-01 ~ V-09
    if format == "json":
        return json.dumps(signal, ensure_ascii=False)
    elif format == "parquet":
        return parquet.write(signal, schema=PARQUET_SCHEMA)
    else:
        raise FormatError(f"Unsupported format: {format}")

def deserialize(data: str/bytes, protocol_version: str = None) -> Signal:
    # 根据 protocol_version 选择解析器
    version = extract_version(data) or protocol_version
    parser = get_parser(version)   # 见 §4.3 降级策略
    validated = parser(data)       # 运行 V-01 ~ V-12
    return Signal(**validated)
```

---

## 2. Version（版本管理）

### 2.1 版本号规则

采用 **Modified SemVer**（自定义语义化版本）：

```
MAJOR.MINOR
```

| 段位 | 递增时机 | 示例 |
|:----|:---------|:-----|
| **MAJOR** | Core 字段新增/删除/类型变更；向后不兼容变更 | `1.0` → `2.0` |
| **MINOR** | extras 规范变更；序列化格式扩展；文档澄清 | `1.0` → `1.1` |

**规则细节**:
- **无 PATCH 段**: PATCH 级别的错误修复通过 MINOR 版本递进表示
- **版本号不包含 `v` 前缀**: `"1.0"` 而非 `"v1.0"`
- **版本比较**: 按数值比较 `MAJOR` 优先，`MINOR` 其次
- 当前版本: `"1.0"`

### 2.2 向后兼容策略

| 变更类型 | MAJOR 升级 | MINOR 升级 | 允许范围 |
|:---------|:----------:|:----------:|:---------|
| Core 新增字段 | ✅ 必须 | ❌ | MAJOR 版本升级时 |
| Core 删除字段 | ✅ 必须 | ❌ | MAJOR 版本升级时 |
| Core 字段类型变更 | ✅ 必须 | ❌ | MAJOR 版本升级时 |
| Core 字段语义变更 | ✅ 推荐 | ⚠️ 需 ADR | MAJOR 或特殊 ADR |
| extras 规范新增 | ❌ | ✅ | MINOR 版本升级时 |
| 序列化格式扩展 | ❌ | ✅ | MINOR 版本升级时 |
| 验证规则收紧 | ✅ 必须 | ❌ | MAJOR 版本升级时 |
| 验证规则放宽 | ❌ | ✅ | MINOR 版本升级时 |

**兼容性定义**:
- **向后兼容**: vN.x Consumer 可以正确消费 vN.y (y ≥ x) 产出的信号
- **向前兼容**: vN.x Consumer 可以降级消费 vN.y (y < x) 产出的信号（见 §4.3）
- **跨 MAJOR 不保证兼容**: v1.x Consumer 不应直接消费 v2.x 信号

### 2.3 字段变更流程

所有协议字段变更必须通过 ADR 流程方为有效。

#### 2.3.1 新增字段（Core）

```
1. 提出 ADR: 描述新字段的名称/类型/用途/默认值
2. Owner 审批
3. 递增 MAJOR 版本（如 1.0 → 2.0）
4. 更新 JSON Schema（附录 B）
5. 更新序列化器
6. Consumer 端并行开发（旧 Consumer 可见新字段但可忽略）
7. 灰度发布（双版本并行 ≥ 2 周）
8. 旧 Consumer 下线 → 字段完成冻结
```

**Core 新增字段必须提供默认值**，确保旧 Consumer 反序列化时不报错。

#### 2.3.2 废弃字段（Core）

```
1. 提出 ADR: 描述废弃原因/迁移方案/降级策略
2. Owner 审批
3. 在字段上添加 @deprecated 标记（protocol_version 递增 MINOR）
4.  Consumer 端逐步迁移（至少在 1 个 MAJOR 版本周期内保留字段）
5. 下一 MAJOR 版本移除字段
```

**废弃字段必须保留至少一个 MAJOR 版本周期**。立即删除被视为破坏性变更。

#### 2.3.3 修改字段（Core）

等价于"先废弃旧字段，再新增新字段"的两个步骤依次执行。不允许"原地修改字段语义"。

#### 2.3.4 extras 规范变更

```
1. 在 signal_protocol_v1.md 的 extras 章节中更新
2. 递增 MINOR 版本（如 1.0 → 1.1）
3. 通知各 Consumer 端
4. 非破坏性变更不需要 ADR
5. 破坏性变更（如禁止某个已广泛使用的 key）需 ADR
```

---

## 3. Lifecycle（信号生命周期）

### 3.1 生命周期状态机

```
                                 ┌────────────────────────────┐
                                 │         GENERATED           │
                                 │  (Research 端产出Signal)    │
                                 └───────────┬────────────────┘
                                             │
                                             ▼
                                 ┌────────────────────────────┐
                                 │        SERIALIZED           │
                                 │  (写入文件/消息队列，持久化) │
                                 └───────────┬────────────────┘
                                             │
                                             ▼
                                 ┌────────────────────────────┐
                                 │        TRANSMITTED          │
                                 │  (从Research传输到Trading)   │
                                 └───────────┬────────────────┘
                                             │
                                             ▼
                                 ┌────────────────────────────┐
                                 │         CONSUMED            │
                                 │  (Consumer读取+执行/暂存)   │
                                 └───────────┬────────────────┘
                                             │
                              ┌──────────────┴──────────────┐
                              │                              │
                              ▼                              ▼
                  ┌────────────────────┐       ┌────────────────────┐
                  │      ARCHIVED      │       │      EXPIRED       │
                  │  (成功消费+归档)    │       │  (超时未消费/过期)  │
                  └────────────────────┘       └────────────────────┘
```

### 3.2 各阶段详细说明

#### Stage 1: GENERATED

- **触发**: Research 端策略引擎完成分析，产出 `Signal` 对象
- **操作**: 
  - 分配 `signal_id` (UUID v4)
  - 填充所有 Core 字段
  - 可选填充 `extras`
  - 记录 `timestamp`
- **负责人**: Research 端（策略引擎 / Signal Generator）
- **超时阈值**: 无（生成即完成）
- **失败处理**: 验证失败则终止生成，记录 error log

#### Stage 2: SERIALIZED

- **触发**: `serialize(signal)` 调用成功
- **操作**:
  - 运行 §1.5 的 V-01 ~ V-09 验证
  - 写入 `.json` / `.jsonl` / `.parquet` 文件
  - **写入后必须 read-back 验证**（墨枢 §3 写入验证规范）
  - 验证失败 → 重试（最多 3 次）→ 写入 `.failed` 标记
- **输出文件路径约定**:
  - 日志（JSON Lines）: `{research_root}/signals/live/{date}/{batch_id}/`
  - 归档（Parquet）: `{research_root}/signals/archive/{date}/`
- **负责人**: Serializer 模块
- **超时阈值**: 生成后 30 秒内必须完成序列化
- **失败处理**: 3 次重试后仍失败 → 写入 `.serialize_failed` 标记，人工干预

#### Stage 3: TRANSMITTED

- **触发**: 信号文件被传输到 Trading 系统的共享目录/消息队列
- **传输机制（v1）**: 文件系统共享（共享目录映射）
  - Research 写入 `{shared}/signals/incoming/{date}/`
  - Trading 轮询读取（默认间隔 1 分钟）
- **传输机制（v2 候选）**: 消息队列（Redis Stream / Kafka）
- **传输可靠性保证**:
  - 文件级: 使用 `.tmp` → rename 原子写入确保 Consumer 不会读到半写文件
  - 幂等: Consumer 端根据 `signal_id` 去重
- **负责人**: 传输层（当前即文件系统）
- **超时阈值**: serialized 后 60 秒内必须完成传输
- **失败处理**: 
  - Research 端: 每 30 秒重试传输，最多 60 分钟
  - 超时未传输 → 直接进入 EXPIRED 分支

#### Stage 4: CONSUMED

- **触发**: Consumer 成功读取信号并完成处理
- **Consumer 处理类型**:
  - **Mapping**: 将 Signal 转换为 OrderRequest 提交交易引擎
  - **暂存**: 信号暂存于 knowledge.db 供策略参考
  - **过滤**: 信号被风控规则过滤（记录过滤原因）
- **消费确认**: Consumer 消费后必须在 `signals/consumed/{date}/` 写入消费记录文件 `consumed_{signal_id}.json`
  ```json
  {
    "signal_id": "<uuid>",
    "consumer": "trading_engine_v1",
    "consumed_at": "2026-05-20T10:31:00+08:00",
    "decision": "EXECUTED / STAGED / FILTERED",
    "reason": "<若被过滤则记录原因>"
  }
  ```
- **负责人**: Trading 端 SignalConsumer
- **超时阈值**: transmitted 后 5 分钟内必须完成消费
- **失败处理**: Consumer 抛异常 → 信号状态回退到 TRANSMITTED → 重试（最多 3 次）

#### Stage 5: ARCHIVED

- **触发**: 信号已成功消费，且无多消费者依赖
- **操作**:
  - 将信号文件从 `signals/incoming/` 移动到 `signals/archive/{date}/`
  - 保留原始数据（不压缩、不截断）
  - 归档文件保留 **90 天**（基线 TTL，具体分类见 ADR-004 §7 差异化策略）
- **归档格式**: 原始 JSON + Parquet 双份
- **负责人**: 日终归档任务

#### Stage 6: EXPIRED

- **触发条件**（任一满足）:
  - 信号生成后超过 horizon 对应的时间阈值未被消费
  - 传输超时（生成后 60 分钟未传输）
  - Consumer 判定信号已过期（如信号 timestamp 早于当前 30 天）
- **操作**:
  - 写入 `signals/expired/{date}/expired_{signal_id}.json` 说明过期原因
  - 不删除原始信号文件，仅标记
- **过期信号归档**: 保留 30 天后自动清除
- **不可逆**: 一旦标记为 EXPIRED，不可重新消费

### 3.3 超时与过期策略

| 状态 | 超时阈值 | 超时后行为 |
|:-----|:---------|:-----------|
| GENERATED | N/A | 无超时 |
| SERIALIZED → TRANSMITTED | 60 秒 | 重新传输（最多 60 分钟） → EXPIRED |
| TRANSMITTED → CONSUMED | 5 分钟 | 3 次重试 → 写入 `.consumer_failed` |
| CONSUMED → ARCHIVED | 当日收盘后 30 分钟 | 日终归档自动执行 |
| 总寿命（GENERATED → EXPIRED） | 按 horizon + 1 天 buffer | short: 4 天 / mid: 31 天 / long: 31 天 |

---

## 4. Compatibility（兼容性保证）

### 4.1 版本兼容矩阵（1.0 vs 1.1）

下表展示 Consumer 版本 × 信号版本的兼容矩阵：

| Consumer ↓ 信号→ | **1.0** | **1.1** | **2.0** |
|:----------------|:-------:|:-------:|:-------:|
| **Consumer v1.0** | ✅ 正常消费 | ⚠️ 降级消费（忽略新字段） | ❌ 不保证 |
| **Consumer v1.1** | ✅ 正常消费 | ✅ 正常消费 | ❌ 不保证 |
| **Consumer v2.0** | ⚠️ 降级消费（默认值填充） | ⚠️ 降级消费（默认值填充） | ✅ 正常消费 |

**规则总结**:
- **跨 MAJOR 不兼容**: v1 Consumer 不应消费 v2 信号（降级方案见 §4.3）
- **同 MAJOR 内向前兼容**: v1.1 Consumer 可以消费 v1.0 信号
- **同 MAJOR 内向后兼容（首选）**: v1.0 Consumer 消费 v1.1 信号时，忽略未知字段
- **MAJOR 降级（第二方案）**: v2.0 Consumer 消费 v1.x 信号时，用默认值填充 v2 新增字段

### 4.2 字段兼容规则

#### 新增字段（同 MAJOR 内 → MINOR 递增）

| 规则 | 说明 | 对旧 Consumer 的影响 |
|:-----|:-----|:--------------------|
| 新 Core 字段必须有默认值 | `None` 或协议定义的合理默认值 | 旧 Consumer 反序列化时可填充默认值 |
| 新 extras 规范键不影响 Core | extras 扩展不改变 Core 字段结构 | 旧 Consumer 正常读取 Core，忽略 extras |
| Parquet schema 必须可读 | 新字段列追加在末尾，旧 Consumer 读时忽略 | 列名前缀不被旧代码识别为已知列 |

#### 废弃字段

| 规则 | 说明 |
|:-----|:------|
| 废弃声明先行 | MINOR 版本标注 `@deprecated`，Consumer 端逐步迁移 |
| 保留至少 1 个 MAJOR 周期 | 废弃字段在下一 MAJOR 版本才删除 |
| 废弃字段必须继续按原格式输出 | 直到正式移除前，不可修改输出内容 |

#### 字段类型变更

| 规则 | 说明 |
|:-----|:------|
| 类型变宽允许 | `int → float`、`enum → str` 允许 MINOR 升级 |
| 类型变窄 | `float → int` 必须 MAJOR 升级 |
| 枚举值新增 | `direction` 新增值（如 `"NONE"`）必须 MAJOR 升级 |
| 枚举值删除 | 必须 MAJOR 升级 |

### 4.3 降级策略

Consumer 遇到不识别的字段或版本号时，按以下优先级降级处理：

#### 策略 A: 字段忽略（默认）

```
条件: Consumer 版本 ≥ 信号的 MAJOR
      且 Consumer 版本 < 信号的 MAJOR.MINOR
行为: 1. 解析所有已知 Core 字段
     2. 忽略所有未知字段（保留在原始数据中）
     3. 尝试解析 extras（若格式匹配）
     4. 日志记录: "Unknown fields ignored: [...]"
     5. 正常处理信号
```

#### 策略 B: 版本降级

```
条件: Consumer 的 MAJOR > 信号的 MAJOR
      或 Consumer 完全无法解析 protocol_version
行为: 1. 检查 signals 文件中的 protocol_version 字段
     2. 若 version > Consumer 支持的版本 → 进入策略 C
     3. 若 version < Consumer 支持的版本 → 按已知 schema 尝试解析
     4. 未知字段用 None 填充（或协议定义的默认值）
     5. 日志记录: "Signal version {v} downgraded to consumer default"
     6. 降级后继续处理
```

#### 策略 C: 信号拒绝

```
条件: Consumer 的 MAJOR ≠ 信号的 MAJOR
      且降级后 Core 字段不完整
行为: 1. 拒绝处理该信号
     2. 写入 signals/rejected/ 下
     3. 日志记录: "Signal {signal_id} rejected: version mismatch (consumer v{x}, signal v{y})"
     4. 不阻塞其他信号消费
```

#### 降级策略优先级

```
Consumer 遇到不识别的版本号时：
  1. 尝试策略 A（字段忽略）：静默忽略未知字段
  2. 若 Core 字段不完整 → 策略 B（版本降级）：用默认值填充
  3. 若降级后仍无法解析 → 策略 C（信号拒绝）：该信号单独拒绝，不阻塞控制
```

### 4.4 兼容性测试用例

以下测试用例覆盖 3 个兼容性场景，作为 Signal Protocol v1 的验收条件。

#### 测试用例 TC-01: 同版本正常消费

```
场景: Consumer v1.0 消费 protocol_version="1.0" 的信号
输入: 符合 v1.0 schema 的标准信号 JSON
预期行为:
  - ✅ 通过 V-01 ~ V-09 验证
  - ✅ 8 个 Core 字段全部正确解析
  - ✅ extras 保留为 dict（可为空）
  - ✅ 信号进入 CONSUMED 状态
```

#### 测试用例 TC-02: 跨 MAJOR 版本拒绝

```
场景: Consumer v1.0 收到 protocol_version="2.0" 的信号
输入: 
  { "signal_id": "...", "symbol": "601857", 
    "direction": "BUY", "confidence": 0.82,
    "horizon": "short", "signal_type": "trend",
    "timestamp": "2026-05-20T10:30:00+08:00",
    "protocol_version": "2.0",
    "extras": {} }
额外: v2.0 新增了 Core 字段 "risk_level": "high"
预期行为:
  - ✅ 触发策略 C（信号拒绝）
  - ✅ 信号写入 signals/rejected/ 下
  - ✅ 日志记录 "version mismatch (consumer v1.0, signal v2.0)"
  - ✅ 同批次中其他 v1.0 信号正常消费
  - ✅ 不阻塞 Consumer 控制流
```

#### 测试用例 TC-03: 同 MAJOR 内未知 extras 键

```
场景: Consumer v1.0 收到协议版本 "1.0"，但 extras 中包含 v1.0 规范外的新键
输入:
  { "signal_id": "...", "symbol": "601857",
    "direction": "BUY", "confidence": 0.82,
    "horizon": "short", "signal_type": "trend",
    "timestamp": "2026-05-20T10:30:00+08:00",
    "protocol_version": "1.0",
    "extras": {
      "ml.ensemble_weight": 0.65,
      "unknown_vendor_feature": "some_value"
    }
  }
预期行为:
  - ✅ 通过 V-01 ~ V-09 验证（extras 内的键不影响 Core）
  - ✅ 8 个 Core 字段全部正确解析
  - ✅ extras 字典原样保留（未丢失数据）
  - ✅ 触发策略 A（字段忽略），日志记录未知 extras 键
  - ✅ 信号进入 CONSUMED 状态
```

#### 测试用例 TC-04: 空字段边界

```
场景: Consumer v1.0 收到 extras 缺失的信号
输入:
  { "signal_id": "...", "symbol": "601857",
    "direction": "BUY", "confidence": 0.82,
    "horizon": "short", "signal_type": "trend",
    "timestamp": "2026-05-20T10:30:00+08:00",
    "protocol_version": "1.0"
  }
  // 注意: 无 extras 字段
预期行为:
  - ✅ 通过 V-01 ~ V-09 验证（extras 非必填）
  - ✅ 反序列化后 extras 自动填为 {} （V-12 自动提升）
  - ✅ 信号进入 CONSUMED 状态
```

#### 测试用例 TC-05: MINOR 版本降级（future-ready）

```
场景: Consumer v1.0 收到 protocol_version="1.1" 的信号
输入: v1.1 格式信号，含 "extra_field": "some_value"（不在 v1.0 Core 中）
预期行为:
  - ✅ 触发策略 A（字段忽略）
  - ✅ 忽略 "extra_field"，正常解析 8 个 Core 字段
  - ✅ extras 字典正常解析
  - ✅ 日志记录 "Unknown fields ignored: ['extra_field']"
  - ✅ 信号进入 CONSUMED 状态
```

---

## 5. 附录

### A. Python 数据类参考实现

```python
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Literal, Optional
import uuid

@dataclass
class Signal:
    # Core（冻结）
    signal_id: str
    symbol: str
    direction: Literal["BUY", "SELL", "HOLD"]
    confidence: float          # 0.0 ~ 1.0, 精度4位
    horizon: str               # "short"|"mid"|"long"
    signal_type: str           # "trend"|"reversal"|"grid"
    timestamp: datetime
    protocol_version: str      # "MAJOR.MINOR"

    # Extension（开放）
    extras: dict = field(default_factory=dict)

    def __post_init__(self):
        """反序列化后自动验证"""
        self.validate()

    def validate(self):
        """运行 V-01 ~ V-09 验证"""
        # V-01: signal_id UUID v4
        try:
            uuid.UUID(self.signal_id, version=4)
        except ValueError:
            raise SchemaValidationError(f"Invalid signal_id: {self.signal_id}")

        # V-02: symbol 非空且≤10字符
        if not self.symbol or len(self.symbol) > 10:
            raise SchemaValidationError(f"Invalid symbol: {self.symbol}")

        # V-03: direction 合法性
        if self.direction not in ("BUY", "SELL", "HOLD"):
            raise SchemaValidationError(f"Invalid direction: {self.direction}")

        # V-04: confidence 范围
        if not (0.0 <= self.confidence <= 1.0):
            raise SchemaValidationError(f"Invalid confidence: {self.confidence}")

        # V-05: horizon 合法性
        if self.horizon not in ("short", "mid", "long"):
            raise SchemaValidationError(f"Invalid horizon: {self.horizon}")

        # V-06: signal_type 合法性
        if self.signal_type not in ("trend", "reversal", "grid"):
            raise SchemaValidationError(f"Invalid signal_type: {self.signal_type}")

        # V-07: timestamp 含时区
        if self.timestamp.tzinfo is None:
            raise SchemaValidationError("timestamp must include timezone offset")

        # V-08: protocol_version 格式
        if not self.protocol_version or "." not in self.protocol_version:
            raise SchemaValidationError(f"Invalid protocol_version: {self.protocol_version}")

        # V-12: extras 类型
        if not isinstance(self.extras, dict):
            raise SchemaValidationError("extras must be a dict")
```

### B. JSON Schema 定义

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "$id": "https://mozhi.internal/signal/v1.0/schema.json",
  "title": "Signal Protocol v1.0",
  "type": "object",
  "required": [
    "signal_id", "symbol", "direction", "confidence",
    "horizon", "signal_type", "timestamp", "protocol_version"
  ],
  "properties": {
    "signal_id": {
      "type": "string",
      "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    },
    "symbol": {
      "type": "string",
      "minLength": 1,
      "maxLength": 10
    },
    "direction": {
      "type": "string",
      "enum": ["BUY", "SELL", "HOLD"]
    },
    "confidence": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "multipleOf": 0.0001
    },
    "horizon": {
      "type": "string",
      "enum": ["short", "mid", "long"]
    },
    "signal_type": {
      "type": "string",
      "enum": ["trend", "reversal", "grid"]
    },
    "timestamp": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\+\\d{2}:\\d{2}$"
    },
    "protocol_version": {
      "type": "string",
      "pattern": "^\\d+\\.\\d+$"
    },
    "extras": {
      "type": "object",
      "default": {},
      "description": "可扩展字典。v1 禁止域见 §1.2 第4条：禁止 Core 替补声明、二进制大数据、敏感信息、循环引用。建议三问：是否属 Core？是否归 knowledge.db？后人能否读懂？"
    }
  },
  "additionalProperties": false
}
```

### C. 协议变更模板（ADR 提案格式）

```markdown
# ADR-NNN: Signal Protocol 变更提案

**标题**: <变更简述>
**提出人**: <Agent 名称>
**日期**: <YYYY-MM-DD>
**变更类型**: <MAJOR | MINOR>
**当前版本**: <当前协议版本>
**目标版本**: <变更后的协议版本>

## 变更概要
<1-3 句话说明变更内容>

## 变更详情
### 新增字段
| 字段 | 类型 | 说明 | 默认值 |
|:-----|:-----|:------|:------:|
| ... | ... | ... | ... |

### 废弃字段
| 字段 | 废弃原因 | 迁移方案 | 保留至版本 |
|:-----|:---------|:---------|:-----------|
| ... | ... | ... | ... |

### 修改字段
| 字段 | 当前 | 目标 | 原因 |
|:-----|:-----|:------|:------|
| ... | ... | ... | ... |

## 兼容性影响
- 向后兼容: ✅ / ❌
- 向前兼容: ✅ / ❌
- 降级策略: <见 §4.3 选用的策略>
- Consumer 影响范围: <哪些 Consumer 需要修改>

## Owner 裁决
<✅ 批准 / ❌ 驳回 / ⏳ 待议>
裁决日期: <YYYY-MM-DD>
```

---

*Signal Protocol v1 完*

**协议签名**:

| 签署方 | 角色 | 结论 | 日期 |
|:------|:-----|:----:|:----:|
| **墨衡** | 协议起草 / 主线架构 | ✅ | 2026-05-20 |
| **墨萱** | 质量门 / 兼容性验证 | ✅ 已签 | 2026-05-20 |
| **墨涵** | 知识归档 / 桥接确认 | ⏳ 待签 | — |
| **Owner** | 业务方向确认 | ✅ 已签 | 2026-05-20 |
