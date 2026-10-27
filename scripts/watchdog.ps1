# Runs under the interactive Windows user via Task Scheduler, once per minute.
# Recovery is process-based; it never kills a running application.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runScript = Join-Path $projectRoot 'run.py'
# Auto-detect Python executable (PATH, project .venv, or local fallback)
$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCmd -and (Test-Path $pythonCmd.Source -PathType Leaf)) {
    $pythonExe = $pythonCmd.Source
} else {
    $venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy -PathType Leaf) {
        $pythonExe = $venvPy
    } else {
        $pythonExe = Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.14-64\python.exe"
    }
}
$logDir = Join-Path $env:LOCALAPPDATA 'OmniKeep\logs'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-WatchdogEvent([string]$message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    Add-Content -Path (Join-Path $logDir 'watchdog.log') -Value $line -Encoding UTF8
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
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/health' -TimeoutSec 4
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
    $portOwners = @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)
    if ($portOwners.Count -gt 0) {
        Write-WatchdogEvent 'Health unavailable; port 5000 belongs to another process. Recovery skipped.'
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
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:5000/health' -TimeoutSec 2
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
