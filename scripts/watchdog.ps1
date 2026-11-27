# Runs under the interactive Windows user via Task Scheduler, once per minute.
# Recovers both crashed processes and hung processes (after consecutive failed /health probes),
# notifying the owner via OmniKeep's configured channels when a hung process is restarted.
# Pure ASCII so Windows PowerShell 5.1 (invoked by watchdog-hidden.vbs) never mis-decodes UTF-8.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-EnvString([string]$name, [string]$defaultValue) {
    $val = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($val)) { return $defaultValue }
    return $val.Trim()
}

function Get-EnvInt([string]$name, [int]$defaultValue, [int]$minValue) {
    $raw = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $defaultValue }
    $parsed = 0
    if ([int]::TryParse($raw.Trim(), [ref]$parsed) -and $parsed -ge $minValue) {
        return $parsed
    }
    return $defaultValue
}

$defaultRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$projectRoot = Get-EnvString 'OMNIKEEP_WATCHDOG_ROOT' $defaultRoot
$runScript = Join-Path $projectRoot 'run.py'

# Auto-detect Python executable (explicit override, project .venv, PATH, or local fallback)
$overridePy = Get-EnvString 'OMNIKEEP_WATCHDOG_PYTHON' ''
$venvPy = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not [string]::IsNullOrWhiteSpace($overridePy) -and (Test-Path $overridePy -PathType Leaf)) {
    $pythonExe = $overridePy
} elseif (Test-Path $venvPy -PathType Leaf) {
    $pythonExe = $venvPy
} elseif ($pythonCmd -and (Test-Path $pythonCmd.Source -PathType Leaf)) {
    $pythonExe = $pythonCmd.Source
} else {
    $pythonExe = Join-Path $env:LOCALAPPDATA "Python\pythoncore-3.14-64\python.exe"
}

$defaultLogDir = Join-Path $env:LOCALAPPDATA 'OmniKeep\logs'
$logDir = Get-EnvString 'OMNIKEEP_WATCHDOG_LOG_DIR' $defaultLogDir
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

$stateFile = Join-Path $logDir 'watchdog-state.json'
$mutexName = Get-EnvString 'OMNIKEEP_WATCHDOG_MUTEX_NAME' 'Local\OmniKeep-Service-Watchdog'
$hangThreshold = Get-EnvInt 'OMNIKEEP_WATCHDOG_HANG_THRESHOLD' 3 1
$startupGraceSec = Get-EnvInt 'OMNIKEEP_WATCHDOG_STARTUP_GRACE_SECONDS' 120 0
$healthTimeoutSec = Get-EnvInt 'OMNIKEEP_WATCHDOG_HEALTH_TIMEOUT_SECONDS' 4 1
$startupWaitAttempts = Get-EnvInt 'OMNIKEEP_WATCHDOG_STARTUP_WAIT_ATTEMPTS' 30 1
$skipOllama = (Get-EnvString 'OMNIKEEP_WATCHDOG_SKIP_OLLAMA' '0') -eq '1'

# Guard against inheriting a short-lived agent runner TEMP/TMP directory (e.g. antigravity-tmp)
# when watchdog.ps1 is invoked manually from an AI coding agent shell instead of Task Scheduler.
function Repair-ProcessTempEnv {
    $needsRepair = $false
    foreach ($val in @($env:TEMP, $env:TMP)) {
        if ([string]::IsNullOrWhiteSpace($val) -or $val -match 'antigravity-tmp' -or -not (Test-Path $val -PathType Container)) {
            $needsRepair = $true
            break
        }
    }
    if (-not $needsRepair) { return }
    $fallback = [Environment]::GetEnvironmentVariable('TEMP', 'User')
    if ([string]::IsNullOrWhiteSpace($fallback) -or $fallback -match 'antigravity-tmp') {
        $fallback = Join-Path $env:LOCALAPPDATA 'Temp'
    }
    New-Item -ItemType Directory -Path $fallback -Force | Out-Null
    $env:TEMP = $fallback
    $env:TMP = $fallback
    if ($env:TMPDIR) { $env:TMPDIR = $fallback }
}
Repair-ProcessTempEnv

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

# Add-Content opens the log read-write; on 2026-11-27 something kept watchdog.log open so that
# only a write-only open succeeded, Add-Content threw, and with ErrorActionPreference Stop that
# aborted a restart halfway (killed, not restarted, owner not told). A write-only append that
# shares everything works then too. Logging must never abort recovery: after 5 tries, give up.
function Write-WatchdogEvent([string]$message) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $message
    $path = Join-Path $logDir 'watchdog.log'
    $bytes = [Text.Encoding]::UTF8.GetBytes($line + "`r`n")
    for ($i = 0; $i -lt 5; $i++) {
        try {
            $fs = New-Object IO.FileStream($path, [IO.FileMode]::Append, [IO.FileAccess]::Write,
                ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
            try {
                $fs.Write($bytes, 0, $bytes.Length)
            } finally {
                $fs.Close()
            }
            return
        } catch {
            Start-Sleep -Milliseconds 100
        }
    }
}

function Read-WatchdogState {
    $result = @{}
    if (-not (Test-Path $stateFile -PathType Leaf)) { return $result }
    try {
        $raw = Get-Content -Raw -Encoding UTF8 $stateFile
        if ([string]::IsNullOrWhiteSpace($raw)) { return $result }
        $obj = $raw | ConvertFrom-Json
        if ($null -eq $obj) { return $result }
        foreach ($prop in $obj.PSObject.Properties) {
            $entry = @{}
            if ($null -ne $prop.Value) {
                foreach ($sub in $prop.Value.PSObject.Properties) {
                    $entry[$sub.Name] = $sub.Value
                }
            }
            $result[$prop.Name] = $entry
        }
    } catch {
        return @{}
    }
    return $result
}

function Write-WatchdogState([hashtable]$state) {
    try {
        $tmp = "$stateFile.tmp"
        $json = $state | ConvertTo-Json -Depth 4
        [IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
        Move-Item -Path $tmp -Destination $stateFile -Force
    } catch {
        Write-WatchdogEvent "Watchdog state write failed ($($_.Exception.GetType().Name))."
    }
}

function Reset-ServiceFailures([string]$serviceKey) {
    $state = Read-WatchdogState
    $prev = 0
    if ($state.ContainsKey($serviceKey) -and $state[$serviceKey].ContainsKey('failures')) {
        $prev = [int]$state[$serviceKey]['failures']
    }
    if ($prev -eq 0 -and $state.ContainsKey($serviceKey)) { return }
    $state[$serviceKey] = @{
        failures = 0
        updated_at = (Get-Date -Format 'o')
    }
    Write-WatchdogState $state
}

function Increment-ServiceFailures([string]$serviceKey) {
    $state = Read-WatchdogState
    $prev = 0
    if ($state.ContainsKey($serviceKey) -and $state[$serviceKey].ContainsKey('failures')) {
        $prev = [int]$state[$serviceKey]['failures']
    }
    $next = $prev + 1
    $state[$serviceKey] = @{
        failures = $next
        updated_at = (Get-Date -Format 'o')
    }
    Write-WatchdogState $state
    return $next
}

function Test-ProcessesPastStartupGrace([object[]]$procs, [int]$graceSeconds) {
    if ($graceSeconds -le 0) { return $true }
    $newest = $null
    foreach ($p in $procs) {
        if ($null -ne $p.CreationDate) {
            try {
                $dt = [datetime]$p.CreationDate
                if ($null -eq $newest -or $dt -gt $newest) { $newest = $dt }
            } catch { }
        }
    }
    if ($null -eq $newest) { return $true }
    $ageSec = ((Get-Date) - $newest).TotalSeconds
    return ($ageSec -ge $graceSeconds)
}

function Stop-HungProcesses([object[]]$procs, [int]$listenPort) {
    $pidList = @()
    foreach ($p in $procs) {
        $pidList += [int]$p.ProcessId
    }
    foreach ($pidVal in $pidList) {
        Stop-Process -Id $pidVal -Force -ErrorAction SilentlyContinue
    }
    # Wait up to 10s for terminated processes to exit and release the port.
    for ($i = 0; $i -lt 20; $i++) {
        $stillAlive = $false
        foreach ($pidVal in $pidList) {
            if ($null -ne (Get-Process -Id $pidVal -ErrorAction SilentlyContinue)) {
                $stillAlive = $true
                break
            }
        }
        $portHeld = @(Get-NetTCPConnection -LocalPort $listenPort -State Listen -ErrorAction SilentlyContinue)
        if (-not $stillAlive -and $portHeld.Count -eq 0) { break }
        Start-Sleep -Milliseconds 500
    }
    return ($pidList -join ',')
}

function Invoke-OwnerRestartAlert([string]$serviceKey, [string]$oldPids, [string]$newPid, [int]$failures, [bool]$recovered) {
    $alertScript = Join-Path $projectRoot 'scripts\alert_owner.py'
    if (-not (Test-Path $alertScript -PathType Leaf)) { return }
    if (-not (Test-Path $pythonExe -PathType Leaf)) { return }
    try {
        $recoveredStr = if ($recovered) { 'true' } else { 'false' }
        $alertKey = "watchdog-restart-$serviceKey-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        # Start-Process in PowerShell 5.1 refuses an empty string inside -ArgumentList, and the
        # "killed but could not restart" path has no new PID: leave such flags out (alert_owner.py
        # defaults them to ""), or the alert most worth sending would never go out.
        $argList = @(
            '-B',
            ('"' + $alertScript + '"'),
            '--event', 'watchdog-restart',
            '--service', $serviceKey
        )
        if (-not [string]::IsNullOrWhiteSpace($oldPids)) { $argList += @('--old-pids', $oldPids) }
        if (-not [string]::IsNullOrWhiteSpace($newPid)) { $argList += @('--new-pid', $newPid) }
        $argList += @(
            '--failures', ([string]$failures),
            '--recovered', $recoveredStr,
            '--key', $alertKey
        )
        $alertProc = Start-Process -FilePath $pythonExe -ArgumentList $argList `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru
        if ($null -ne $alertProc) {
            if (-not $alertProc.WaitForExit(20000)) {
                Stop-Process -Id $alertProc.Id -Force -ErrorAction SilentlyContinue
                Write-WatchdogEvent "Owner restart alert timed out for $serviceKey."
            }
        }
    } catch {
        Write-WatchdogEvent "Owner restart alert failed for $serviceKey ($($_.Exception.GetType().Name))."
    }
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
    if ($skipOllama) { return }
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

# The local OpenAI-compatible endpoint (run_gateway.py, app/llm_gateway.py) that lets claude-mem
# use the Vertex AI connections. It runs only where llm_gateway.json exists (made by
# scripts/llm_gateway_setup.py), and apart from run.py, so either can restart alone.
function Ensure-Gateway {
    $configFile = Join-Path $projectRoot 'llm_gateway.json'
    if (-not (Test-Path $configFile -PathType Leaf)) { return }
    $gatewayPort = 5101
    try {
        $config = Get-Content -Raw -Encoding UTF8 $configFile | ConvertFrom-Json
        if ($config.PSObject.Properties.Name -contains 'port') { $gatewayPort = [int]$config.port }
    } catch {
        Write-WatchdogEvent 'llm_gateway.json cannot be read; using port 5101.'
    }
    $gwHealthUrl = "http://127.0.0.1:$gatewayPort/health"
    try {
        $health = Invoke-RestMethod -Uri $gwHealthUrl -TimeoutSec $healthTimeoutSec
        if ($health.status -eq 'healthy' -and $health.service -eq 'OmniKeep LLM gateway') {
            Reset-ServiceFailures 'gateway'
            return
        }
    } catch { }
    $gatewayScript = Join-Path $projectRoot 'run_gateway.py'
    if (-not (Test-Path $gatewayScript -PathType Leaf)) { return }
    $escaped = [regex]::Escape($gatewayScript)
    $running = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match $escaped })
    $restartedFromHang = $false
    $hungOldPids = ''
    $hungFailCount = 0
    if ($running.Count -gt 0) {
        if (-not (Test-ProcessesPastStartupGrace $running $startupGraceSec)) {
            Write-WatchdogEvent "Gateway starting up (within grace window); existing process PID $($running[0].ProcessId)."
            return
        }
        $hungFailCount = Increment-ServiceFailures 'gateway'
        if ($hungFailCount -lt $hangThreshold) {
            Write-WatchdogEvent "Gateway not answering ($hungFailCount/$hangThreshold); process still running (PID $($running[0].ProcessId))."
            return
        }
        $hungOldPids = Stop-HungProcesses $running $gatewayPort
        Reset-ServiceFailures 'gateway'
        $restartedFromHang = $true
        Write-WatchdogEvent "Gateway hung ($hungFailCount/$hangThreshold); terminated PID(s) $hungOldPids for restart."
    }
    $owners = @(Get-NetTCPConnection -LocalPort $gatewayPort -State Listen -ErrorAction SilentlyContinue)
    if ($owners.Count -gt 0) {
        Write-WatchdogEvent "Gateway port $gatewayPort belongs to another process. Start skipped."
        if ($restartedFromHang) {
            Invoke-OwnerRestartAlert 'gateway' $hungOldPids '' $hungFailCount $false
        }
        return
    }
    if (-not (Test-Path $pythonExe -PathType Leaf)) { return }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
    $proc = Start-Process -FilePath $pythonExe -ArgumentList @('-B', ('"' + $gatewayScript + '"')) `
        -WorkingDirectory $projectRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "gateway-$stamp.stdout.log") `
        -RedirectStandardError (Join-Path $logDir "gateway-$stamp.stderr.log") -PassThru
    Write-WatchdogEvent "Started the LLM gateway (PID $($proc.Id)) on port $gatewayPort; logs: gateway-$stamp.*.log"
    if ($restartedFromHang) {
        $gwRecovered = $false
        for ($attempt = 0; $attempt -lt $startupWaitAttempts; $attempt++) {
            Start-Sleep -Seconds 2
            if ($proc.HasExited) { break }
            try {
                $health = Invoke-RestMethod -Uri $gwHealthUrl -TimeoutSec 2
                if ($health.status -eq 'healthy' -and $health.service -eq 'OmniKeep LLM gateway') {
                    $gwRecovered = $true
                    break
                }
            } catch { }
        }
        Invoke-OwnerRestartAlert 'gateway' $hungOldPids ([string]$proc.Id) $hungFailCount $gwRecovered
    }
}

$mutex = [System.Threading.Mutex]::new($false, $mutexName)
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
        Ensure-Gateway
    } catch {
        Write-WatchdogEvent "Gateway check failed ($($_.Exception.GetType().Name))."
    }

    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec $healthTimeoutSec
        if ($response.status -eq 'healthy' -and $response.service -eq 'OmniKeep') {
            Reset-ServiceFailures 'omnikeep'
            return
        }
    } catch {
        # Unavailable health endpoint: check ownership before starting or restarting hung process.
    }

    # A slow startup must not cause a second copy of the application; a truly hung process is restarted after threshold.
    $escapedRunScript = [regex]::Escape($runScript)
    $appProcess = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match $escapedRunScript })
    $restartedFromHang = $false
    $hungOldPids = ''
    $hungFailCount = 0
    if ($appProcess.Count -gt 0) {
        if (-not (Test-ProcessesPastStartupGrace $appProcess $startupGraceSec)) {
            Write-WatchdogEvent "Health unavailable while OmniKeep is starting up (PID $($appProcess[0].ProcessId)). Waiting."
            return
        }
        $hungFailCount = Increment-ServiceFailures 'omnikeep'
        if ($hungFailCount -lt $hangThreshold) {
            Write-WatchdogEvent "Health unavailable ($hungFailCount/$hangThreshold); existing OmniKeep process still running (PID $($appProcess[0].ProcessId))."
            return
        }
        $hungOldPids = Stop-HungProcesses $appProcess $port
        Reset-ServiceFailures 'omnikeep'
        $restartedFromHang = $true
        Write-WatchdogEvent "OmniKeep hung ($hungFailCount/$hangThreshold); terminated PID(s) $hungOldPids for restart."
    }

    # Do not steal another service's TCP port or launch conflicting instances.
    $portOwners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($portOwners.Count -gt 0) {
        Write-WatchdogEvent "Health unavailable; port $port belongs to another process. Recovery skipped."
        if ($restartedFromHang) {
            Invoke-OwnerRestartAlert 'omnikeep' $hungOldPids '' $hungFailCount $false
        }
        return
    }

    if (-not (Test-Path $pythonExe -PathType Leaf)) {
        Write-WatchdogEvent 'Python runtime missing; recovery skipped.'
        if ($restartedFromHang) {
            Invoke-OwnerRestartAlert 'omnikeep' $hungOldPids '' $hungFailCount $false
        }
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
    $recovered = $false
    for ($attempt = 0; $attempt -lt $startupWaitAttempts; $attempt++) {
        Start-Sleep -Seconds 2
        if ($proc.HasExited) {
            Write-WatchdogEvent "OmniKeep exited during startup (exit code $($proc.ExitCode))."
            break
        }
        try {
            $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
            if ($response.status -eq 'healthy' -and $response.service -eq 'OmniKeep') {
                Write-WatchdogEvent "OmniKeep healthy (PID $($proc.Id))."
                Reset-ServiceFailures 'omnikeep'
                $recovered = $true
                break
            }
        } catch {
            # Startup is still in progress.
        }
    }
    if (-not $recovered -and -not $proc.HasExited) {
        Write-WatchdogEvent "OmniKeep startup health check timed out (PID $($proc.Id))."
    }
    if ($restartedFromHang) {
        Invoke-OwnerRestartAlert 'omnikeep' $hungOldPids ([string]$proc.Id) $hungFailCount $recovered
    }
} catch {
    # Avoid leaking request URLs/credentials in error messages.
    Write-WatchdogEvent "Watchdog failed ($($_.Exception.GetType().Name))."
} finally {
    if ($ownsMutex) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
