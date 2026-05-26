<#
.SYNOPSIS
    Verify registered MoShu scheduled tasks. Outputs a green/red status table.
.DESCRIPTION
    Queries schtasks for all MoShu-* tasks and compares against config/scheduler.json.
.NOTES
    Read-only operation, no admin required.
#>

[CmdletBinding()]
param(
    [string]$ConfigPath = "$PSScriptRoot\..\config\scheduler.json"
)

$ErrorActionPreference = "Continue"

$ColorGreen  = "Green"
$ColorRed    = "Red"
$ColorYellow = "Yellow"
$ColorCyan   = "Cyan"
$ColorGray   = "Gray"

function Write-StatusLine {
    param([string]$Label, [string]$Value, [string]$Color)
    Write-Host ("  {0,-30} " -f $Label) -NoNewline -ForegroundColor $ColorGray
    Write-Host $Value -ForegroundColor $Color
}

Write-Host "==============  MoShu Scheduled Task Verification  ==============" -ForegroundColor White
Write-Host ""

# 1. Read expected tasks from config
$expectedTasks = @()
if (Test-Path $ConfigPath) {
    $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    $expectedTasks = $config | Where-Object { $_.enabled } | ForEach-Object { "MoShu-$($_.id)" }
    Write-Host "[Config] Loaded $($config.Count) task definitions" -ForegroundColor $ColorCyan
    Write-Host "         Expected active tasks: $($expectedTasks.Count)" -ForegroundColor $ColorCyan
} else {
    Write-Host "[WARN] Config not found: $ConfigPath -- skipping expected-task check" -ForegroundColor $ColorYellow
}
Write-Host ""

# 2. Query registered tasks
Write-Host "[Query] Fetching registered MoShu scheduled tasks..." -ForegroundColor $ColorGray

$rawOutput = schtasks /query /fo LIST /v /tn "MoShu-*" 2>&1
$queryExit = $LASTEXITCODE

if ($queryExit -ne 0) {
    Write-Host ""
    Write-Host "  No MoShu tasks found or query failed" -ForegroundColor $ColorRed
    Write-Host "  Run as admin: .\scripts\install_windows_scheduler.ps1" -ForegroundColor $ColorGray
    exit 1
}

# 3. Parse schtasks output
$taskInfo = @{}
$currentTask = $null

foreach ($line in $rawOutput) {
    if ($line -match '^' + [regex]::Escape("TaskName:") + '\s+(MoShu-.+)$') {
        $currentTask = $matches[1]
        if (-not $taskInfo.ContainsKey($currentTask)) {
            $taskInfo[$currentTask] = @{}
        }
    }
    elseif ($currentTask -and $line -match '^' + [regex]::Escape("Status:") + '\s+(.+)$') {
        $taskInfo[$currentTask]['Status'] = $matches[1].Trim()
    }
    elseif ($currentTask -and $line -match '^' + [regex]::Escape("Next Run Time:") + '\s+(.+)$') {
        $taskInfo[$currentTask]['NextRun'] = $matches[1].Trim()
    }
    elseif ($currentTask -and $line -match '^' + [regex]::Escape("Schedule:") + '\s+(.+)$') {
        $taskInfo[$currentTask]['Schedule'] = $matches[1].Trim()
    }
}

# Also try English field names
$currentTask = $null
foreach ($line in $rawOutput) {
    if ($line -match '^TaskName:\s+(MoShu-.+)$') {
        $currentTask = $matches[1]
        if (-not $taskInfo.ContainsKey($currentTask)) {
            $taskInfo[$currentTask] = @{}
        }
    }
    elseif ($currentTask -and $line -match '^Status:\s+(.+)$') {
        $taskInfo[$currentTask]['Status'] = $matches[1].Trim()
    }
    elseif ($currentTask -and $line -match '^Next Run Time:\s+(.+)$') {
        $taskInfo[$currentTask]['NextRun'] = $matches[1].Trim()
    }
    elseif ($currentTask -and $line -match '^Schedule:\s+(.+)$') {
        $taskInfo[$currentTask]['Schedule'] = $matches[1].Trim()
    }
}

# 4. Display status table
Write-Host ""
Write-Host ("{0,-6} {1,-22} {2,-10} {3,-18}" -f "  #", "Task Name", "Status", "Next Run") -ForegroundColor White
Write-Host ("{0,-6} {1,-22} {2,-10} {3,-18}" -f "  --", "---------", "------", "--------") -ForegroundColor Gray

$idx = 0
$foundTasks = $taskInfo.Keys | Sort-Object
foreach ($name in $foundTasks) {
    $idx++
    $info = $taskInfo[$name]
    $status = if ($info['Status']) { $info['Status'] } else { "Unknown" }
    $nextRun = if ($info['NextRun']) { $info['NextRun'] } else { "-" }

    $sColor = if     ($status -eq 'Ready')   { $ColorGreen }
                  elseif ($status -match '^J')    { $ColorGreen }  # Chinese locale: status starts with 'J'
                  elseif ($status -eq 'Running')  { $ColorCyan  }
                  elseif ($status -match 'Disabled') { $ColorYellow }
                  else                         { $ColorRed    }

    Write-Host ("  {0,-3} {1,-22} " -f $idx, $name) -NoNewline
    Write-Host ("{0,-10}" -f $status) -NoNewline -ForegroundColor $sColor
    Write-Host ("{0,-18}" -f $nextRun)
}

Write-Host ""
Write-Host "Found $idx MoShu task(s)" -ForegroundColor White

# 5. Completeness check
Write-Host ""
Write-Host "--------------  Completeness Check  --------------" -ForegroundColor White

$missingTasks = @()
foreach ($expected in $expectedTasks) {
    if (-not $taskInfo.ContainsKey($expected)) {
        $missingTasks += $expected
    }
}

if ($missingTasks.Count -eq 0 -and $expectedTasks.Count -gt 0) {
    Write-Host "  All expected tasks are registered" -ForegroundColor $ColorGreen
} elseif ($missingTasks.Count -gt 0) {
    Write-Host "  Missing tasks:" -ForegroundColor $ColorRed
    foreach ($m in $missingTasks) {
        Write-Host "    $m" -ForegroundColor $ColorYellow
    }
}

# Extra tasks (not in config)
$extraTasks = @()
foreach ($name in $foundTasks) {
    if ($name -notin $expectedTasks) {
        $extraTasks += $name
    }
}

if ($extraTasks.Count -gt 0) {
    Write-Host "  Extra tasks (not in config):" -ForegroundColor $ColorYellow
    foreach ($e in $extraTasks) {
        Write-Host "    $e"
    }
}

Write-Host ""
Write-Host "--------------------------------------------------" -ForegroundColor White

$allReady = $foundTasks.Count -gt 0 -and ($missingTasks.Count -eq 0)
if ($allReady) {
    Write-Host "  Status: OK - All tasks ready" -ForegroundColor $ColorGreen
    exit 0
} else {
    Write-Host "  Status: WARNING - Check issues above" -ForegroundColor $ColorYellow
    exit 1
}
