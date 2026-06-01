<#
.SYNOPSIS
  Send CI failure notification to Feishu group via bot webhook.
.DESCRIPTION
  Posts an interactive card message to Feishu when a CI workflow step fails.
  Intended to be called only on `if: failure()` or `if: cancelled()` in GitHub Actions.
.PARAMETER WebhookUrl
  Feishu bot webhook URL (full URL with token).
.PARAMETER WorkflowName
  Name of the workflow (e.g. "PR CI", "Daily Full Regression").
.PARAMETER TriggerEvent
  Triggering event (push, pull_request, schedule, workflow_dispatch).
.PARAMETER Branch
  Branch name (e.g. "master", "refs/heads/feature/xxx").
.PARAMETER CommitSha
  Short commit SHA (first 7 characters).
.PARAMETER CommitUrl
  Full URL to the commit on GitHub.
.PARAMETER RunId
  GitHub Actions run ID (numeric).
.PARAMETER RunUrl
  Full URL to the workflow run on GitHub.
.PARAMETER FailedStep
  Name of the step that failed (if known).
.PARAMETER Actor
  GitHub user who triggered the run.
.PARAMETER Repo
  Repository full name (e.g. "Tiger2106/mozhi").
.PARAMETER Summary
  Optional additional summary text.
.EXAMPLE
  .\scripts\feishu_ci_notify.ps1 -WebhookUrl $env:FEISHU_CI_WEBHOOK `
    -WorkflowName "PR CI" -TriggerEvent "push" -Branch "master" `
    -CommitSha "abc1234" -CommitUrl "https://github.com/Tiger2106/mozhi/commit/abc1234" `
    -RunId "12345" -RunUrl "https://github.com/Tiger2106/mozhi/actions/runs/12345" `
    -FailedStep "Verify Import" -Actor "tiger" -Repo "Tiger2106/mozhi"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$WebhookUrl,

    [Parameter(Mandatory = $true)]
    [string]$WorkflowName,

    [Parameter(Mandatory = $true)]
    [string]$TriggerEvent,

    [Parameter(Mandatory = $true)]
    [string]$Branch,

    [Parameter(Mandatory = $true)]
    [string]$CommitSha,

    [Parameter(Mandatory = $true)]
    [string]$CommitUrl,

    [Parameter(Mandatory = $true)]
    [string]$RunId,

    [Parameter(Mandatory = $true)]
    [string]$RunUrl,

    [Parameter(Mandatory = $true)]
    [string]$FailedStep,

    [Parameter(Mandatory = $true)]
    [string]$Actor,

    [Parameter(Mandatory = $true)]
    [string]$Repo,

    [Parameter(Mandatory = $false)]
    [string]$Summary = ""
)

$ErrorActionPreference = "Stop"

# Map trigger event to Chinese label
$eventMap = @{
    "push"             = "推送"
    "pull_request"     = "合并请求"
    "schedule"         = "定时任务"
    "workflow_dispatch" = "手动触发"
}
$eventLabel = if ($eventMap.ContainsKey($TriggerEvent)) { $eventMap[$TriggerEvent] } else { $TriggerEvent }

# Build Feishu interactive card
$body = @{
    msg_type = "interactive"
    card = @{
        header = @{
            title = @{
                tag     = "plain_text"
                content = "❌ CI 运行失败 — $WorkflowName"
            }
            template = "red"
        }
        elements = @(
            @{
                tag  = "markdown"
                content = "**仓库：** [$Repo](https://github.com/$Repo)`n**分支：** $Branch`n**触发：** $eventLabel`n**提交：** [$CommitSha]($CommitUrl)`n**触发者：** $Actor`n**失败步骤：** **$FailedStep**"
            },
            @{
                tag = "hr"
            },
            @{
                tag  = "markdown"
                content = "**Run ID：** $RunId`n**运行时间：** $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')"
            },
            @{
                tag = "hr"
            },
            @{
                tag  = "action"
                actions = @(
                    @{
                        tag  = "button"
                        text = @{
                            tag     = "plain_text"
                            content = "🔍 查看详情"
                        }
                        url   = $RunUrl
                        type  = "default"
                    }
                )
            }
        )
    }
} | ConvertTo-Json -Depth 10 -Compress

try {
    $response = Invoke-RestMethod -Uri $WebhookUrl -Method Post -Body $body -ContentType "application/json" -TimeoutSec 15
    if ($response.code -ne 0) {
        Write-Error "Feishu webhook returned error code: $($response.code) - $($response.msg)"
        exit 1
    }
    Write-Host "Feishu notification sent successfully."
} catch {
    Write-Error "Failed to send Feishu notification: $_"
    exit 1
}
