# stock-auditor Windows 安装脚本（PowerShell 5.1+ / PowerShell 7+）
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Backfill -Autostart

[CmdletBinding()]
param(
    [switch]$Backfill,
    [switch]$Autostart
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Uv {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$UvArguments)
    & uv @UvArguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令失败（退出码 $LASTEXITCODE）：uv $($UvArguments -join ' ')"
    }
}

Write-Host "==> 检查 uv"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw @"
未找到 uv。请先安装：
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
安装后重新打开终端，再执行本脚本。
"@
}

Write-Host "==> 安装依赖（uv sync --frozen）"
Invoke-Uv sync --frozen

if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "==> 已生成 .env；请填写 LLM_API_KEY、飞书等密钥后再运行 sa doctor"
}

Write-Host "==> 建库并执行迁移"
Invoke-Uv run sa init

if ($Backfill) {
    Write-Host "==> 回填历史数据（可中断，重复执行会续传）"
    Invoke-Uv run sa init --backfill
}

Write-Host "==> 检查环境（缺少密钥时只提示，不阻断安装）"
& uv run sa doctor
if ($LASTEXITCODE -ne 0) {
    Write-Warning "doctor 有未通过项；填好 .env 与 config/local/ 后重新执行：uv run sa doctor"
}

if ($Autostart) {
    Write-Host "==> 安装开机自启"
    Invoke-Uv run sa autostart install
}

Write-Host ""
Write-Host "安装完成。常用命令："
Write-Host "  uv run sa doctor                    环境自检"
Write-Host "  uv run sa ingest                    采集数据"
Write-Host "  uv run sa run weekly --refresh      生成周报"
Write-Host "  uv run sa serve                     常驻运行（定时任务 + 飞书）"