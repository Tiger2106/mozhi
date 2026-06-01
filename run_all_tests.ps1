<#
.SYNOPSIS
  Run all test suites sequentially (avoid sys.path namespace conflicts).
#>

param([switch]$CollectOnly)

$ErrorActionPreference = "Continue"
$Root = "C:\Users\17699\mozhi_platform"
$Ok = @()
$Ng = @()
$Suites = @(
    @{Name="core";       Path="$Root\tests";                         Args=@("$Root\src\backtest\tests")},
    @{Name="verify_001"; Path="$Root\archive\verify_20260601\verify_001\tests"; Args=@()},
    @{Name="verify_002"; Path="C:\Users\17699\mo_zhi_sharereports\verify_002\tests"; Args=@()},
    @{Name="verify_003"; Path="C:\Users\17699\verify_003\tests";     Args=@()}
)

foreach ($s in $Suites) {
    Write-Host "--- [$($s.Name)] $($s.Path) ---"
    $pargs = @("--tb=short", "-p", "no:cacheprovider")
    if ($CollectOnly) { $pargs += "--collect-only" }
    $pargs += "-q"
    $pargs += $s.Args
    $pargs += $s.Path

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $r = & python -m pytest $pargs 2>&1 | Out-String
    $sw.Stop()
    $summary = ($r -split "`n")[-3..-2] -join "; "
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  OK  ($($sw.Elapsed.TotalSeconds.ToString('F1'))s) $summary" -ForegroundColor Green
        $Ok += $s.Name
    } else {
        Write-Host "  FAIL ($($sw.Elapsed.TotalSeconds.ToString('F1'))s) $summary" -ForegroundColor Yellow
        $Ng += $s.Name
    }
}

Write-Host "--- SUMMARY ---"
Write-Host "Ok: $($Ok.Count) | Fail: $($Ng.Count)"
if ($Ok) { Write-Host "  OK: $($Ok -join ', ')" -ForegroundColor Green }
if ($Ng) { Write-Host "  FAIL: $($Ng -join ', ')" -ForegroundColor Red }
if ($Ng.Count -gt 0) { exit 1 }
