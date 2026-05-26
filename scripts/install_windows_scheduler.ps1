<#
.SYNOPSIS
    Read config/scheduler.json and register each enabled task as a Windows Scheduled Task.
.DESCRIPTION
    Convert cron expression to schtasks triggers (supports daily/weekdays/weekly).
    Task name format: MoShu-{id}. Log output goes to logs/scheduler/{id}.log.
.NOTES
    Requires Administrator privileges.
#>

[CmdletBinding()]
param(
    [string]$ConfigPath = "$PSScriptRoot\..\config\scheduler.json"
)

$ErrorActionPreference = "Stop"
$LogDir = "$PSScriptRoot\..\logs\scheduler"

# Helper: convert cron expression to schtasks parameters
function Convert-CronToSchtasks {
    param([string]$Cron)

    $parts = $Cron -split '\s+'
    if ($parts.Count -ne 5) {
        throw "Invalid cron expression: '$Cron' - need 5 fields"
    }

    $min      = $parts[0]
    $hour     = $parts[1]
    $dow      = $parts[4]  # day-of-week

    if ($dow -match '^\d+([-/,]\d+)*$') {
        # numeric format
        $scheduleType = "WEEKLY"
        $map = @{0="SUN";1="MON";2="TUE";3="WED";4="THU";5="FRI";6="SAT";7="SUN"}
        $days = $dow -split ',' | ForEach-Object {
            $_.Trim() -split '-' | ForEach-Object { $map[[int]$_] }
        }
        $daysOfWeek = ($days | Select-Object -Unique) -join ','
    } elseif ($dow -eq '*') {
        $scheduleType = "DAILY"
        $daysOfWeek   = $null
    } else {
        throw "Unsupported day-of-week format: '$dow'"
    }

    $time = "$($hour.PadLeft(2,'0')):$($min.PadLeft(2,'0'))"

    switch ($scheduleType) {
        "DAILY" {
            return @("/SC", "DAILY", "/ST", $time, "/F")
        }
        "WEEKLY" {
            return @("/SC", "WEEKLY", "/D", $daysOfWeek, "/ST", $time, "/F")
        }
        default {
            throw "Unknown schedule type: $scheduleType"
        }
    }
}

# Ensure log directory
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Read config
if (-not (Test-Path $ConfigPath)) {
    Write-Error "Config file not found: $ConfigPath"
    exit 1
}
$tasks = Get-Content $ConfigPath -Raw | ConvertFrom-Json

# Register tasks
$results = @()
foreach ($task in $tasks) {
    if (-not $task.enabled) {
        Write-Host "[SKIP] $($task.id) -- disabled" -ForegroundColor Gray
        continue
    }

    $taskName  = "MoShu-$($task.id)"
    $logFile   = Join-Path $LogDir "$($task.id).log"
    $actionCmd = $task.command
    $actionCwd = $task.cwd

    Write-Host "[INFO] Processing task: $taskName" -ForegroundColor Cyan

    # Check if already exists
    $existing = schtasks /query /tn $taskName 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  -> Task exists, updating..." -ForegroundColor Yellow
        $changeFlag = "/CHANGE"
    } else {
        Write-Host "  -> Creating new task..." -ForegroundColor Green
        $changeFlag = "/CREATE"
    }

    # Convert cron to schtasks args
    try {
        $triggerArgs = Convert-CronToSchtasks -Cron $task.cron
    } catch {
        Write-Error "  -> cron conversion failed: $_"
        $results += [PSCustomObject]@{ Task = $taskName; Status = "FAILED"; Detail = $_.Exception.Message }
        continue
    }

    # Build wrapped command that sets CWD and redirects output to log
    $wrappedCmd = "cmd /c `"cd /d $actionCwd && $actionCmd >> `"$logFile`" 2>&1`""

    $schtaskArgs = @(
        $changeFlag
        "/TN", $taskName
        "/TR", $wrappedCmd
        "/RL", "HIGHEST"
    ) + $triggerArgs

    if ($changeFlag -eq "/CREATE") {
        $schtaskArgs += @("/RU", "SYSTEM")
    }

    # Execute
    $output = & "schtasks" $schtaskArgs 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        $statusMsg = if ($changeFlag -eq "/CREATE") { "CREATED" } else { "UPDATED" }
        Write-Host "  -> $statusMsg OK" -ForegroundColor Green
        $results += [PSCustomObject]@{ Task = $taskName; Status = $statusMsg; Detail = "" }
    } else {
        Write-Host "  -> FAILED" -ForegroundColor Red
        $results += [PSCustomObject]@{ Task = $taskName; Status = "FAILED"; Detail = ($output -join '; ') }
    }
}

# Summary
Write-Host ""
Write-Host "=============  Registration Summary  =============" -ForegroundColor White
$results | Format-Table -AutoSize | Out-Host

$failed = $results | Where-Object { $_.Status -eq "FAILED" }
if ($failed) {
    Write-Host "[WARN] Tasks with failures:" -ForegroundColor Yellow
    $failed | ForEach-Object { Write-Host "  FAILED $($_.Task): $($_.Detail)" -ForegroundColor Red }
} else {
    Write-Host "[OK] All tasks registered successfully" -ForegroundColor Green
}
