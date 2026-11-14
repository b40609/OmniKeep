# Runs under the interactive Windows user via Task Scheduler, once per minute.
# Recovery is process-based; it never kills a running application.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runScript = Join-Path $projectRoot 'run.py'
# Auto-detect Python executable (project .venv from install.ps1, PATH, or local fallback)
$venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if (Test-Path $venvPy -PathType Leaf) {
    $pythonExe = $venvPy
} elseif ($pythonCmd -and (Test-Path $pythonCmd.Source -PathType Leaf)) {
    $pythonExe = $pythonCmd.Source
} else {
    $pythonExe = Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.14-64\python.exe"
}
$logDir = Join-Path $env:LOCALAPPDATA 'OmniKeep\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

# The port the service listens on: PORT in .env, 5000 when it is not set there.
function Get-ServicePort([string]$root) {
    $envFile = Join-Path $root '.env'
    if (Test-Path $envFile -PathType Leaf) {
        foreach ($line in [IO.File]::ReadAllLines($envFile)) {
            if ($line -match '^\s*PORT\s*=\s*["'']?(\d{1,5})["'']?\s*(#.*)?$') { return [int]$Matches[1] }
        }
    }
    return 5000
}
$port = Get-ServicePort $projectRoot
$healthUrl = "http://127.0.0.1:$port/health"

function Write-WatchdogEvent([string]$message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    Add-Content -Path (Join-Path $logDir 'watchdog.log') -Value $line -Encoding UTF8
}

# Ollama serves the embeddings and Ask Brain. Its Windows tray app starts the server only at logon,
# and when that server stops (it did several times in 2026-11, leaving no crash report) nothing
# brings it back: search went without vectors for a day. On a machine where Ollama is installed,
# a stopped server is started again here, with its output kept so the next stop can be explained.
function Find-OllamaExe {
    $cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path $cmd.Source -PathType Leaf)) { return $cmd.Source }
    $default = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $default -PathType Leaf) { return $default }
    return $null
}

function Ensure-Ollama {
    $ollamaExe = Find-OllamaExe
    if (-not $ollamaExe) { return }   # not installed here: nothing to look after
    try {
        Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 4 | Out-Null
        return
    } catch {
        # Not answering: start it only if nothing holds the port (a busy server is left alone).
    }
    $listening = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)
    if ($listening.Count -gt 0) {
        Write-WatchdogEvent "Ollama not answering; port 11434 is held (PID $($listening[0].OwningProcess)). Left alone."
        return
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
    $out = Join-Path $logDir "ollama-$stamp.stdout.log"
    $err = Join-Path $logDir "ollama-$stamp.stderr.log"
    $proc = Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Write-WatchdogEvent "Ollama was down; started 'ollama serve' (PID $($proc.Id)); logs: ollama-$stamp.*.log"
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        Start-Sleep -Seconds 2
        if ($proc.HasExited) {
            Write-WatchdogEvent "Ollama exited during startup (exit code $($proc.ExitCode))."
            return
        }
        try {
            Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null
            Write-WatchdogEvent "Ollama healthy (PID $($proc.Id))."
            return
        } catch { }
    }
    Write-WatchdogEvent "Ollama startup health check timed out (PID $($proc.Id))."
}

$mutex = [System.Threading.Mutex]::new($false, 'Local\OmniKeep-Service-Watchdog')
$ownsMutex = $false
try {
    try {
        $ownsMutex = $mutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $ownsMutex = $true
    }
    if (-not $ownsMutex) { return }

    try {
        Ensure-Ollama
    } catch {
        Write-WatchdogEvent "Ollama check failed ($($_.Exception.GetType().Name))."
    }

    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 4
        if ($response.status -eq 'healthy' -and $response.service -eq 'OmniKeep') {
            return
        }
    } catch {
        # Unavailable health endpoint: check ownership before starting.
    }

    # A slow startup must not cause a second copy of the application.
    $escapedRunScript = [regex]::Escape($runScript)
    $appProcess = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match $escapedRunScript })
    if ($appProcess.Count -gt 0) {
        Write-WatchdogEvent "Health unavailable; existing OmniKeep process still running (PID $($appProcess[0].ProcessId))."
        return
    }

    # Do not steal another service's TCP port or launch conflicting instances.
    $portOwners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($portOwners.Count -gt 0) {
        Write-WatchdogEvent "Health unavailable; port $port belongs to another process. Recovery skipped."
        return
    }

    if (-not (Test-Path $pythonExe -PathType Leaf)) {
        Write-WatchdogEvent 'Python runtime missing; recovery skipped.'
        return
    }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
    $stdout = Join-Path $logDir "service-$stamp.stdout.log"
    $stderr = Join-Path $logDir "service-$stamp.stderr.log"
    $proc = Start-Process -FilePath $pythonExe -ArgumentList @('-B', ('"' + $runScript + '"')) `
        -WorkingDirectory $projectRoot -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    Write-WatchdogEvent "Started OmniKeep (PID $($proc.Id)); logs: service-$stamp.*.log"

    # Hold the mutex until service is healthy or has failed to start.
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 2
        if ($proc.HasExited) {
            Write-WatchdogEvent "OmniKeep exited during startup (exit code $($proc.ExitCode))."
            return
        }
        try {
            $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
            if ($response.status -eq 'healthy' -and $response.service -eq 'OmniKeep') {
                Write-WatchdogEvent "OmniKeep healthy (PID $($proc.Id))."
                return
            }
        } catch {
            # Startup is still in progress.
        }
    }
    Write-WatchdogEvent "OmniKeep startup health check timed out (PID $($proc.Id))."
} catch {
    # Avoid leaking request URLs/credentials in error messages.
    Write-WatchdogEvent "Watchdog failed ($($_.Exception.GetType().Name))."
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
