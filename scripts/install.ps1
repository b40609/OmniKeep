<#
.SYNOPSIS
OmniKeep 安裝腳本（Windows）。

.DESCRIPTION
檢查 git、Python 3.12+、Node.js 20.19+；clone、建立 .venv、安裝依賴、產生 .env、
建置前端、建立 watchdog 排程（每分鐘檢查、登入時啟動）、啟動服務，
最後把 stdio MCP 與 omnikeep-setup Skill 註冊到 Claude Code、Codex、Antigravity。

可以重複執行：已完成的步驟會略過，不會覆寫既有的 .env 或資料庫。

一行安裝（PowerShell）：
  & ([scriptblock]::Create((irm https://raw.githubusercontent.com/b40609/OmniKeep/main/scripts/install.ps1)))

先看會做什麼：
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1 -DryRun

.PARAMETER InstallDir
安裝位置。預設：從 repo 內執行時用這個 repo；否則 $HOME\OmniKeep。

.PARAMETER DryRun
只列出會做的事，不改任何東西（包含不 clone、不註冊 agent）。

.PARAMETER InstallPrereqs
缺少 git、Python、Node.js 時用 winget 安裝。

.PARAMETER Force
watchdog 排程已存在、但指向別的資料夾時，改成指向這次的安裝。

.PARAMETER Agents
只註冊這些 agent，逗號分隔：claude,codex,antigravity。預設：偵測到的全部。

.PARAMETER AgentHome
改用別的家目錄註冊 agent（測試用）；指定時直接寫設定檔，不呼叫 claude、codex 指令。
#>
[CmdletBinding()]
param(
    [string]$InstallDir,
    [string]$Repo = 'https://github.com/b40609/OmniKeep.git',
    [string]$Branch = 'main',
    [switch]$DryRun,
    [switch]$InstallPrereqs,
    [switch]$NoStart,
    [switch]$NoWatchdog,
    [switch]$NoRegister,
    [switch]$Force,
    [string]$Agents,
    [string]$AgentHome
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskName = 'OmniKeep Watchdog'
$HealthUrl = 'http://127.0.0.1:5000/health'
$MinPython = [version]'3.12'

function Write-Step([string]$message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Note([string]$message) { Write-Host "    $message" }
function Write-Warn([string]$message) { Write-Host "    [注意] $message" -ForegroundColor Yellow }

function Invoke-Action([string]$description, [scriptblock]$action) {
    if ($DryRun) {
        Write-Host "    [dry-run] $description" -ForegroundColor DarkGray
        return
    }
    Write-Note $description
    & $action
}

function Invoke-Native([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "指令失敗（exit $LASTEXITCODE）：$exe $($arguments -join ' ')"
    }
}

function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
}

# ── 1. 檢查必要工具 ──────────────────────────────────────────────

function Find-Python {
    $candidates = @(
        @{ Exe = 'py'; Args = @('-3') },
        @{ Exe = 'python'; Args = @() },
        @{ Exe = 'python3'; Args = @() }
    )
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        try {
            # No double quotes: Windows PowerShell 5.1 strips them from native-command arguments.
            $probe = @($candidate.Args) + @('-c', 'import sys; print(*sys.version_info[:2], sep=chr(46)); print(sys.executable)')
            $output = @(& $candidate.Exe @probe 2>$null)
            if ($LASTEXITCODE -ne 0 -or $output.Count -lt 2) { continue }
            $version = [version]$output[0].Trim()
            if ($version -ge $MinPython) {
                return @{ Exe = $output[1].Trim(); Version = $version }
            }
        } catch {
            continue
        }
    }
    return $null
}

function Test-NodeVersion([string]$text) {
    if ($text -notmatch '^v?(\d+)\.(\d+)') { return $false }
    $major = [int]$Matches[1]; $minor = [int]$Matches[2]
    # Vite 7 needs Node 20.19+ or 22.12+.
    if ($major -eq 20) { return $minor -ge 19 }
    if ($major -eq 22) { return $minor -ge 12 }
    return $major -ge 23
}

function Get-Prerequisites {
    $result = @{ Missing = @(); Python = $null }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) { $result.Missing += 'git' }
    $result.Python = Find-Python
    if (-not $result.Python) { $result.Missing += 'python' }
    $node = Get-Command node -ErrorAction SilentlyContinue
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $node -or -not $npm -or -not (Test-NodeVersion ((& node --version) 2>$null))) {
        $result.Missing += 'node'
    }
    return $result
}

$WingetIds = @{ git = 'Git.Git'; python = 'Python.Python.3.14'; node = 'OpenJS.NodeJS.LTS' }

Write-Step '檢查 git、Python 3.12+、Node.js 20.19+'
$prereq = Get-Prerequisites
if ($prereq.Missing.Count -gt 0) {
    $commands = $prereq.Missing | ForEach-Object {
        "winget install --id $($WingetIds[$_]) -e --accept-source-agreements --accept-package-agreements"
    }
    if ($InstallPrereqs -and -not $DryRun) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw '找不到 winget，請手動安裝：' + ($prereq.Missing -join '、')
        }
        foreach ($name in $prereq.Missing) {
            Write-Note "用 winget 安裝 $name（$($WingetIds[$name])）"
            Invoke-Native 'winget' @('install', '--id', $WingetIds[$name], '-e',
                '--accept-source-agreements', '--accept-package-agreements')
        }
        Update-SessionPath
        $prereq = Get-Prerequisites
        if ($prereq.Missing.Count -gt 0) {
            throw ('安裝後仍找不到：' + ($prereq.Missing -join '、') + '。請開新的終端機再執行一次。')
        }
    } elseif ($DryRun) {
        Write-Warn ('缺少：' + ($prereq.Missing -join '、') + '。實際執行時需要先安裝：')
        $commands | ForEach-Object { Write-Note $_ }
    } else {
        Write-Host ('缺少：' + ($prereq.Missing -join '、') + '。可以加 -InstallPrereqs 自動安裝，或手動執行：') -ForegroundColor Red
        $commands | ForEach-Object { Write-Host "  $_" }
        exit 1
    }
}
if ($prereq.Python) { Write-Note "Python $($prereq.Python.Version)：$($prereq.Python.Exe)" }
if (Get-Command node -ErrorAction SilentlyContinue) { Write-Note "Node.js $((& node --version) 2>$null)" }

# ── 2. 取得程式碼 ────────────────────────────────────────────────

function Test-OmniKeepRepo([string]$path) {
    return $path -and (Test-Path (Join-Path $path 'run.py') -PathType Leaf) -and
        (Test-Path (Join-Path $path 'mcp_server.py') -PathType Leaf)
}

if (-not $InstallDir) {
    $scriptRepo = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { $null }
    $InstallDir = if (Test-OmniKeepRepo $scriptRepo) { $scriptRepo } else { Join-Path $HOME 'OmniKeep' }
}
$InstallDir = [IO.Path]::GetFullPath($InstallDir)

Write-Step "取得程式碼：$InstallDir"
if (Test-OmniKeepRepo $InstallDir) {
    Write-Note '已經有 OmniKeep，略過 clone（不會自動更新；要更新請自己 git pull）。'
} elseif ((Test-Path $InstallDir) -and @(Get-ChildItem -Force $InstallDir).Count -gt 0) {
    throw "$InstallDir 已存在而且不是空的，也不是 OmniKeep。請換一個 -InstallDir。"
} else {
    Invoke-Action "git clone --branch $Branch $Repo `"$InstallDir`"" {
        Invoke-Native 'git' @('clone', '--branch', $Branch, $Repo, $InstallDir)
    }
}

$VenvPython = Join-Path $InstallDir '.venv\Scripts\python.exe'

# ── 3. Python 依賴 ───────────────────────────────────────────────

Write-Step '建立 .venv 並安裝 Python 依賴（第一次約需幾分鐘）'
if (Test-Path $VenvPython -PathType Leaf) {
    Write-Note '.venv 已存在。'
} else {
    $basePython = if ($prereq.Python) { $prereq.Python.Exe } else { 'python' }
    Invoke-Action "`"$basePython`" -m venv .venv" {
        Invoke-Native $basePython @('-m', 'venv', (Join-Path $InstallDir '.venv'))
    }
}
Invoke-Action 'pip install -r requirements.txt' {
    Invoke-Native $VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '--upgrade', 'pip')
    Invoke-Native $VenvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', (Join-Path $InstallDir 'requirements.txt'))
}

# ── 4. 首次設定檔 ────────────────────────────────────────────────

Write-Step '產生 .env（只在不存在時；存取金鑰隨機產生，不會顯示）'
if (Test-Path (Join-Path $InstallDir '.env')) {
    Write-Note '.env 已存在，不覆寫。'
} else {
    Invoke-Action 'python scripts\bootstrap_env.py' {
        Invoke-Native $VenvPython @((Join-Path $InstallDir 'scripts\bootstrap_env.py'), '--project-dir', $InstallDir)
    }
}

# ── 5. 前端 ──────────────────────────────────────────────────────

Write-Step '建置前端（npm ci、npm run build）'
$frontendDir = Join-Path $InstallDir 'frontend'
Invoke-Action 'npm ci; npm run build' {
    Push-Location $frontendDir
    try {
        Invoke-Native 'npm' @('ci', '--no-audit', '--no-fund')
        Invoke-Native 'npm' @('run', 'build')
    } finally {
        Pop-Location
    }
}

# ── 6. watchdog 排程 ─────────────────────────────────────────────

$VbsPath = Join-Path $InstallDir 'scripts\watchdog-hidden.vbs'
$VbsContent = @'
Option Explicit

Dim shell, files, quote, watchdog, powerShellExe, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

quote = Chr(34)
watchdog = files.BuildPath(files.GetParentFolderName(WScript.ScriptFullName), "watchdog.ps1")
powerShellExe = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
command = quote & powerShellExe & quote & " -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy RemoteSigned -File " & quote & watchdog & quote
result = shell.Run(command, 0, True)
WScript.Quit result
'@

$watchdogReady = $false
if ($NoWatchdog) {
    Write-Step '略過 watchdog（-NoWatchdog）'
} else {
    Write-Step "建立 watchdog 排程「$TaskName」（每分鐘檢查、登入時啟動）"
    if (Test-Path $VbsPath -PathType Leaf) {
        Write-Note 'watchdog-hidden.vbs 已存在。'
    } else {
        Invoke-Action '產生 scripts\watchdog-hidden.vbs（不進 git）' {
            [IO.File]::WriteAllText($VbsPath, ($VbsContent -replace "`r?`n", "`r`n") + "`r`n", [Text.Encoding]::ASCII)
        }
    }

    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $pointsHere = $false
    if ($existing) {
        $pointsHere = @($existing.Actions | Where-Object { $_.Arguments -and $_.Arguments.Contains($VbsPath) }).Count -gt 0
    }
    if ($existing -and $pointsHere) {
        Write-Note '排程已存在並指向這次的安裝。'
        $watchdogReady = $true
    } elseif ($existing -and -not $Force) {
        Write-Warn "排程「$TaskName」已存在，但指向別的資料夾；沒有改動。要改成這次的安裝，加 -Force 重跑。"
    } else {
        Invoke-Action "Register-ScheduledTask `"$TaskName`" → wscript `"$VbsPath`"" {
            $action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\wscript.exe') `
                -Argument "//B //Nologo `"$VbsPath`""
            $everyMinute = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
                -RepetitionInterval (New-TimeSpan -Minutes 1)
            $atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
            $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
                -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
            $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
                -LogonType Interactive -RunLevel Limited
            Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($everyMinute, $atLogon) `
                -Settings $settings -Principal $principal -Force | Out-Null
        }
        $watchdogReady = $true
    }
}

# ── 7. 啟動 ──────────────────────────────────────────────────────

function Test-Health {
    try {
        $response = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3
        return ($response.status -eq 'healthy' -and $response.service -eq 'OmniKeep')
    } catch {
        return $false
    }
}

if ($NoStart) {
    Write-Step '略過啟動（-NoStart）'
} else {
    Write-Step '啟動 OmniKeep'
    if (-not $DryRun -and (Test-Health)) {
        Write-Note "已經有 OmniKeep 在 $HealthUrl 執行。"
    } elseif ($watchdogReady) {
        Invoke-Action "Start-ScheduledTask `"$TaskName`"" { Start-ScheduledTask -TaskName $TaskName }
    } else {
        Invoke-Action '在背景執行 .venv\Scripts\python.exe run.py' {
            $logDir = Join-Path $env:LOCALAPPDATA 'OmniKeep\logs'
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
            Start-Process -FilePath $VenvPython -ArgumentList @('-B', "`"$(Join-Path $InstallDir 'run.py')`"") `
                -WorkingDirectory $InstallDir -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $logDir "service-$stamp.stdout.log") `
                -RedirectStandardError (Join-Path $logDir "service-$stamp.stderr.log") | Out-Null
        }
    }
    if (-not $DryRun) {
        $healthy = $false
        for ($i = 0; $i -lt 45 -and -not $healthy; $i++) {
            Start-Sleep -Seconds 2
            $healthy = Test-Health
        }
        if ($healthy) {
            Write-Note "OmniKeep 已啟動：http://127.0.0.1:5000"
        } else {
            Write-Warn "90 秒內沒等到 $HealthUrl 回應。看 %LOCALAPPDATA%\OmniKeep\logs 的 service-*.stderr.log。"
        }
    }
}

# ── 8. 註冊到 agent ──────────────────────────────────────────────

if ($NoRegister) {
    Write-Step '略過 agent 註冊（-NoRegister）'
} else {
    Write-Step '註冊 MCP 與 Skill 到 Claude Code、Codex、Antigravity'
    $registerScript = Join-Path $InstallDir 'scripts\register_agents.py'
    $RegisterArgs = @()
    if ($Agents) { $RegisterArgs += @('--agents', $Agents) }
    if ($AgentHome) { $RegisterArgs += @('--home', $AgentHome) }
    if ($DryRun -and (Test-Path $registerScript -PathType Leaf)) {
        $runner = if (Test-Path $VenvPython -PathType Leaf) { $VenvPython } elseif ($prereq.Python) { $prereq.Python.Exe } else { 'python' }
        Invoke-Native $runner (@($registerScript, '--project-dir', $InstallDir, '--python', $VenvPython, '--dry-run') + $RegisterArgs)
    } else {
        Invoke-Action "python scripts\register_agents.py --project-dir `"$InstallDir`"" {
            Invoke-Native $VenvPython (@($registerScript, '--project-dir', $InstallDir, '--python', $VenvPython) + $RegisterArgs)
        }
    }
}

Write-Host ''
if ($DryRun) {
    Write-Host '以上是 dry-run，沒有改動任何東西。' -ForegroundColor Green
} else {
    Write-Host '安裝完成。' -ForegroundColor Green
    Write-Host '下一步：開一個新的 agent session（Claude Code、Codex 或 Antigravity），說「幫我設定 OmniKeep」。'
}
