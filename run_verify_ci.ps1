<#
.SYNOPSIS
  墨枢 CI 回归测试运行脚本
  Run all VERIFY regression suites + workspace-moheng/tests sequentially.

.DESCRIPTION
  Runs pytest across these test suites:
    - core:        mozhi_platform\tests + src\backtest\tests
    - moheng:      workspace-moheng\tests
    - verify_001:  archive\verify_20260601\verify_001\tests
    - verify_002:  mo_zhi_sharereports\verify_002\tests
    - verify_003:  verify_003\tests

  Each suite runs in its own python -m pytest invocation to avoid
  sys.path / namespace conflicts.

.PARAMETER CollectOnly
  Only collect (list) tests, don't execute them.

.PARAMETER XmlReport
  Generate JUnit-style XML reports under tests\_junit_{suite}.xml.

.PARAMETER Verbose
  Show verbose pytest output (-v) instead of default quiet.

.PARAMETER SkipCore
  Skip the core (mozhi_platform\tests) suite — useful when iterating
  on verify suites alone.

.PARAMETER SkipMoheng
  Skip the workspace-moheng\tests suite.

.PARAMETER SkipVerify
  Skip all VERIFY suites.

.EXAMPLE
  .\run_verify_ci.ps1

.EXAMPLE
  .\run_verify_ci.ps1 -CollectOnly

.EXAMPLE
  .\run_verify_ci.ps1 -XmlReport -Verbose
#>

param(
  [switch]$CollectOnly,
  [switch]$XmlReport,
  [switch]$Verbose,
  [switch]$SkipCore,
  [switch]$SkipMoheng,
  [switch]$SkipVerify
)

$ErrorActionPreference = "Continue"
$Root      = "C:\Users\17699\mozhi_platform"
$Moheng    = "C:\Users\17699\.openclaw\workspace-moheng"
$Share     = "C:\Users\17699\mo_zhi_sharereports"
$Verify003 = "C:\Users\17699\verify_003"
$PassSuites = @()
$FailSuites = @()

# ── Build suite list ──────────────────────────────────────
$Suites = @()

if (-not $SkipCore) {
  $Suites += @{
    Name = "core"
    Paths = @("$Root\tests", "$Root\src\backtest\tests")
    Label = "墨枢核心 $Root\tests + src\backtest\tests"
  }
}

if (-not $SkipMoheng) {
  $Suites += @{
    Name = "moheng"
    Paths = @("$Moheng\tests")
    Label = "墨衡 $Moheng\tests"
  }
}

if (-not $SkipVerify) {
  $Suites += @{
    Name = "verify_001"
    Paths = @("$Root\archive\verify_20260601\verify_001\tests")
    Label = "VERIFY-001 动量/反转/前向收益因子基线 $Root\archive\verify_20260601\verify_001\tests"
  }
  $Suites += @{
    Name = "verify_002"
    Paths = @("$Share\verify_002\tests")
    Label = "VERIFY-002 截面IC计算基线 $Share\verify_002\tests"
  }
  $Suites += @{
    Name = "verify_003"
    Paths = @("$Verify003\tests")
    Label = "VERIFY-003 随机因子噪声基线 $Verify003\tests"
  }
}

if ($Suites.Count -eq 0) {
  Write-Host "No suites selected (all skipped). Nothing to do." -ForegroundColor Yellow
  exit 0
}

# ── Run each suite ─────────────────────────────────────────
$StartAll = [System.Diagnostics.Stopwatch]::StartNew()

foreach ($s in $Suites) {
  Write-Host "`n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
  Write-Host "  [$($s.Name)] $($s.Label)" -ForegroundColor Cyan
  Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan

  # Build pytest args
  $pargs = @("--tb=short", "-p", "no:cacheprovider")
  if ($Verbose) { $pargs += "-v" } else { $pargs += "-q" }
  if ($CollectOnly) { $pargs += "--collect-only" }
  if ($XmlReport) {
    $xmlPath = "$Root\tests\_junit_$($s.Name).xml"
    $pargs += "--junitxml=$xmlPath"
    Write-Host "  JUnit XML -> $xmlPath" -ForegroundColor DarkGray
  }
  # Append test paths
  $pargs += $s.Paths

  $sw = [System.Diagnostics.Stopwatch]::StartNew()

  if ($CollectOnly) {
    # collect-only: capture output for display
    $r = & python -m pytest $pargs 2>&1 | Out-String
    $sw.Stop()
    Write-Host $r
    $nd = ($r -split "`n")[-2..-1] -join "  "
    Write-Host "  COLLECT DONE  ($($sw.Elapsed.TotalSeconds.ToString('F1'))s)  $nd" -ForegroundColor Cyan
    $PassSuites += $s.Name
    continue
  }

  # Normal run
  $r = & python -m pytest $pargs 2>&1 | Out-String
  $sw.Stop()

  # Parse summary line
  $summary = ""
  $lastLines = ($r -split "`n") | Select-Object -Last 3
  foreach ($line in $lastLines) {
    if ($line -match '\d+ passed|FAILED|ERROR|no tests ran') {
      $summary = $line.Trim()
    }
  }

  if ($LASTEXITCODE -eq 0) {
    Write-Host "  [PASS] ($($sw.Elapsed.TotalSeconds.ToString('F1'))s)  $summary" -ForegroundColor Green
    $PassSuites += $s.Name
  } else {
    Write-Host "  [FAIL] ($($sw.Elapsed.TotalSeconds.ToString('F1'))s)  $summary" -ForegroundColor Red
    $FailSuites += $s.Name
    # Show first few failure lines
    $failLines = $r -split "`n" | Where-Object { $_ -match 'FAILED|ERROR' }
    if ($failLines) {
      Write-Host "  Errors:" -ForegroundColor DarkRed
      $failLines | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkRed }
    }
  }
}

$StartAll.Stop()
$ElapsedAll = $StartAll.Elapsed.TotalSeconds.ToString('F1')

# ── Summary ────────────────────────────────────────────────
$PassCount = $PassSuites.Count
$FailCount = $FailSuites.Count
$TotalSuites = $Suites.Count

Write-Host "`n═══════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  CI REGRESSION SUMMARY" -ForegroundColor Cyan
Write-Host "  Total suites: $TotalSuites | PASS: $PassCount | FAIL: $FailCount" -ForegroundColor Cyan
Write-Host "  Duration: ${ElapsedAll}s" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════" -ForegroundColor Cyan

if ($PassCount -gt 0) { Write-Host "  [PASS] $($PassSuites -join ', ')" -ForegroundColor Green }
if ($FailCount -gt 0) { Write-Host "  [FAIL] $($FailSuites -join ', ')" -ForegroundColor Red }

if ($FailCount -eq 0 -and $TotalSuites -gt 0) {
  Write-Host "`nAll suites passed." -ForegroundColor Green
} else {
  Write-Host "`nSome suites failed." -ForegroundColor Yellow
}

# Exit code: 0 if all passed, 1 if any failed
if ($FailCount -gt 0) { exit 1 }
