# 墨枢 CI 运行指引

> **编制**：墨衡 | **版本**：v1.0 | **日期**：2026-06-01
> 
> **适用范围**：墨枢投资系统 VERIFY 回归测试 (core + moheng + verify_001/002/003)
> 
> **代码仓库**：`C:\Users\17699\mozhi_platform`

---

## 一、概览

墨枢 CI 回归测试覆盖以下 5 个测试套件，按顺序依次执行：

| 套件名称 | 测试路径 | 说明 |
|:--------:|:---------|:-----|
| `core` | `mozhi_platform\tests` + `src\backtest\tests` | 墨枢核心功能测试 |
| `moheng` | `workspace-moheng\tests` | 墨衡模块测试 |
| `verify_001` | `archive\verify_20260601\verify_001\tests` | 动量/反转/前向收益因子基线 |
| `verify_002` | `mo_zhi_sharereports\verify_002\tests` | 截面 IC 计算基线 |
| `verify_003` | `verify_003\tests` | 随机因子噪声基线 |

每个套件在独立 `python -m pytest` 进程中运行，避免 sys.path / namespace 冲突。

---

## 二、本地运行

### 2.1 快速启动（推荐 — 批处理）

```batch
.\run_verify_ci.bat
```

批处理在 PowerShell 不可用时也能运行，并自动执行 **两步流程**：
1. **收集（Collect-Only）**：先以 dry-run 模式验证所有测试可发现
2. **执行**：收集通过后，正式运行所有测试套件

### 2.2 PowerShell 脚本（直接调用）

```powershell
.\run_verify_ci.ps1
```

PowerShell 脚本提供更丰富的参数控制。

```powershell
# 仅收集测试（dry-run），不执行
.\run_verify_ci.ps1 -CollectOnly

# 生成 JUnit XML 报告 + 详细输出
.\run_verify_ci.ps1 -XmlReport -Verbose

# 跳过核心测试（调试 verify 套件时）
.\run_verify_ci.ps1 -SkipCore

# 跳过墨衡测试
.\run_verify_ci.ps1 -SkipMoheng

# 跳过所有 VERIFY 套件（仅跑核心 + 墨衡）
.\run_verify_ci.ps1 -SkipVerify
```

### 2.3 参数说明

#### 当前支持的参数

| 参数 | 类型 | 默认值 | 说明 |
|:----:|:----:|:------:|:-----|
| `-CollectOnly` | `[switch]` | off | 仅收集/列举测试，不执行任何用例 |
| `-XmlReport` | `[switch]` | off | 在每个套件目录下生成 `_junit_{suite_name}.xml` 报告 |
| `-Verbose` | `[switch]` | off | 使用 `-v` 详细输出模式（默认 `-q` 静默模式） |
| `-SkipCore` | `[switch]` | off | 跳过 core 套件（墨枢核心测试） |
| `-SkipMoheng` | `[switch]` | off | 跳过 moheng 套件（墨衡测试） |
| `-SkipVerify` | `[switch]` | off | 跳过所有 VERIFY 套件（001/002/003） |

#### 计划中参数（下一版本）

以下参数为规划中的增强功能，当前脚本暂不支持：

| 参数 | 类型 | 默认值 | 说明 |
|:----:|:----:|:------:|:-----|
| `-Suite` | `string[]` | 全部 | 指定要运行的套件名称（如 `-Suite core,moheng`），支持通配符 `-Suite verify_*` |
| `-Parallel` | `[int]` | 1 | 并行执行的套件数。`-Parallel 2` 表示最多同时跑 2 个套件。需配合 `pytest-xdist` 使用 |
| `-SkipCoverage` | `[switch]` | off | 跳过覆盖率收集。当 `-Parallel` 启用时自动生效，避免并行覆盖率竞争 |

**设计意图：**
- `-Suite`：替代逐个 `-Skip*` 参数，使用白名单模式更灵活
- `-Parallel`：缩短总执行时间，特别适合各套件互不依赖的场景
- `-SkipCoverage`：并行时关闭覆盖率以避免 `.coverage` 文件写入冲突

---

## 三、CI/CD 工作流

### 3.1 GitHub Actions（规划中）

> **备注**：当前 CI 以本地执行为主，GitHub Actions 工作流文件 (.github/workflows/) 为后续规划。

**触发条件（建议）：**

```yaml
on:
  push:
    branches: [main, develop]
    paths:
      - 'src/**'
      - 'mozhi_platform/**'
      - 'workspace-moheng/**'
      - 'requirements.txt'
      - '.github/workflows/**'
  pull_request:
    branches: [main, develop]
  workflow_dispatch:  # 手动触发
```

**工作流阶段（建议）：**

```
Stage 1: 环境准备
  └─ Python 3.10 / 3.11 矩阵安装
  └─ 依赖安装 (pip install -e .)

Stage 2: 测试收集（dry-run）
  └─ .\run_verify_ci.ps1 -CollectOnly

Stage 3: 回归执行
  └─ .\run_verify_ci.ps1 -XmlReport

Stage 4: 覆盖率报告
  └─ python -m coverage report --fail-under=95

Stage 5: 结果归档
  └─ JUnit XML 报告上传
  └─ 覆盖率 HTML 报告上传
```

### 3.2 本地 CI 手动触发

```batch
:: 完整回归（开发机推荐）
.\run_verify_ci.bat

:: 快速验证（仅核心 + 墨衡，跳过 VERIFY）
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { & '.\run_verify_ci.ps1' -SkipVerify; exit $LASTEXITCODE }"

:: 仅收集 + XML 报告
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { & '.\run_verify_ci.ps1' -CollectOnly -XmlReport; exit $LASTEXITCODE }"
```

### 3.3 验收标准（墨萱要求）

墨萱在 Week 2 周五验收时确认以下 CI 检查点：

- [ ] 本地 `.\run_verify_ci.bat` 一次通过（全部 5 套件）
- [ ] 覆盖率 ≥ 95%（`coverage_html/` 目录）
- [ ] 所有 JUnit XML 报告可生成
- [ ] CI 失败阻止合并机制就绪

---

## 四、故障排查常见问题

### Q1: 批处理报错 "PowerShell not found"

**原因**：系统 PATH 中找不到 PowerShell 可执行文件。

**解决**：
```powershell
# 确认 PowerShell 安装路径
where powershell

# 若不存在，尝试绝对路径运行
powershell -NoProfile -ExecutionPolicy Bypass -File .\run_verify_ci.ps1
```

### Q2: 批处理报错 "Script not found"

**原因**：从非 `mozhi_platform` 根目录运行，或脚本被移动。

**解决**：
```batch
:: 先切换到脚本所在目录
cd /d C:\Users\17699\mozhi_platform
.\run_verify_ci.bat
```

### Q3: 测试套件全部跳过

**原因**：同时使用了多个 `-Skip*` 参数导致无套件可选。

**解决**：检查参数组合，至少保留一个套件。当前设计允许全部跳过（输出 "No suites selected" 并正常退出）。

### Q4: VERIFY 套件找不到测试目录

**原因**：VERIFY-001/002/003 数据文件尚未部署或路径变更。

**检查方法**：
```powershell
# 确认各测试目录存在
Test-Path "C:\Users\17699\mozhi_platform\archive\verify_20260601\verify_001\tests"
Test-Path "C:\Users\17699\mo_zhi_sharereports\verify_002\tests"
Test-Path "C:\Users\17699\verify_003\tests"
```

**解决**：联系墨萱确认基线数据部署状态，或使用 `-SkipVerify` 跳过后单独验证。

### Q5: pytest 报 "No module named ..."

**原因**：依赖未安装或 Python 虚拟环境未激活。

**解决**：
```powershell
# 确认所有依赖就绪
pip install -e C:\Users\17699\mozhi_platform

# 确认 Python 解释器版本
python --version  # 需 >= 3.10

# 若使用虚拟环境，先激活
# .venv\Scripts\Activate.ps1
```

### Q6: 测试执行时间过长

**预期时间**：
| 场景 | 预估耗时 |
|:----|:--------:|
| Collect-only | ~30s |
| 完整回归（5 套件） | ~10-20 min |
| 仅 core + moheng | ~5-10 min |
| 仅 VERIFY 套件 | ~5-10 min |

**优化建议**：
```powershell
# 开发调试时跳过耗时 suite
.\run_verify_ci.ps1 -SkipVerify

# 或仅跑特定套件（下一版本支持 -Suite）
```

### Q7: JUnit XML 报告未生成

**原因**：未使用 `-XmlReport` 参数，或目标目录无写入权限。

**解决**：
```powershell
# 确保传入 -XmlReport 参数
.\run_verify_ci.ps1 -XmlReport

# 检查报告输出目录
Test-Path "C:\Users\17699\mozhi_platform\tests\_junit_*.xml"
```

### Q8: 覆盖率低于 95%

**原因**：新增代码未覆盖，或覆盖率配置文件过时。

**解决**：
```bash
# 生成覆盖率报告查看缺失行
python -m coverage html
# 打开 coverage_html/index.html 查看具体未覆盖代码

# 确认 fail-under 阈值
# 参见 pyproject.toml [tool.coverage.report] fail_under = 95
```

---

## 五、附录

### A. 脚本文件结构

```
mozhi_platform/
├── run_verify_ci.bat        # 批处理入口（两步流程）
├── run_verify_ci.ps1        # PowerShell 主脚本
├── pyproject.toml            # 项目配置（含覆盖率设置）
└── tests/                    # 核心测试目录
    ├── _junit_core.xml       # JUnit 报告（生成）
    ├── _junit_moheng.xml     #
    ├── _junit_verify_001.xml #
    ├── _junit_verify_002.xml #
    └── _junit_verify_003.xml #
```

### B. 版本历史

| 版本 | 日期 | 变更 |
|:----:|:----:|:-----|
| v1.0 | 2026-06-01 | 初始版本，覆盖本地运行 + CI 流程 + 故障排查 |
