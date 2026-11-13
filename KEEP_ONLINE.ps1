# KEEP_ONLINE.ps1 - keeps the SIID-01 system live on the internet from this PC.
#
# - Runs the backend (dashboard + API) on http://127.0.0.1:5000
# - Runs the ngrok link at http://frill-relay-nacho.ngrok-free.dev (the address
#   baked into firmware/card/card.ino, so the card needs no reflash)
# - Checks both every 15 seconds and restarts whichever one stopped
# - Stops Windows from idle-sleeping while it runs (power settings are not changed;
#   closing the laptop lid or choosing Sleep still sleeps the PC)
#
# Start: KEEP_ONLINE.cmd      Stop: STOP_ONLINE.cmd      Log: tmp\keep-online.log

$ErrorActionPreference = 'Continue'
$root       = $PSScriptRoot
$backendDir = Join-Path $root 'backend'
$python     = Join-Path $backendDir 'venv\Scripts\python.exe'
$tmp        = Join-Path $root 'tmp'
$stopFlag   = Join-Path $tmp 'stop-online.flag'
$logFile    = Join-Path $tmp 'keep-online.log'
$pidFile    = Join-Path $tmp 'keep-online.pid'
$publicUrl  = 'http://frill-relay-nacho.ngrok-free.dev'

New-Item -ItemType Directory -Path $tmp -Force | Out-Null
Remove-Item -LiteralPath $stopFlag -ErrorAction SilentlyContinue
Set-Content -LiteralPath $pidFile -Value $PID
$env:PYTHONUNBUFFERED = '1'

# The live dashboard is on the public internet, so it must not use the demo
# password printed in the README. Put the real one in tmp\siid-admin-password.txt
# (tmp\ is never committed). Without that file the backend falls back to the demo login.
$adminPasswordFile = Join-Path $tmp 'siid-admin-password.txt'
if (Test-Path -LiteralPath $adminPasswordFile) {
    $env:SIID_ADMIN_PASSWORD = (Get-Content -LiteralPath $adminPasswordFile -Raw).Trim()
}

Add-Type -Namespace SiidOnline -Name Power -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
# ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x1): no idle sleep while this runs.
$keepAwake = [uint32]2147483649

function Write-Log([string]$Message) {
    Add-Content -LiteralPath $logFile -Value ("{0:yyyy-MM-dd HH:mm:ss}  {1}" -f (Get-Date), $Message)
}

function Test-Url([string]$Url) {
    try { return (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 4).StatusCode -eq 200 }
    catch { return $false }
}

function Test-Tunnel {
    try {
        $t = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 4
        return @($t.tunnels | Where-Object { $_.public_url -like '*frill-relay-nacho*' }).Count -gt 0
    } catch { return $false }
}

function Stop-Backend {
    # The venv python.exe is a launcher that starts the real interpreter as a child,
    # so stop both the launcher and whatever is actually listening on port 5000.
    $ids = @()
    $ids += Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*app.py*' -and $_.ExecutablePath -like "$backendDir*" } |
        ForEach-Object { $_.ProcessId }
    $ids += Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { $_.OwningProcess }
    $ids | Where-Object { $_ -and $_ -ne 0 } | Select-Object -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
}

function Stop-Ngrok {
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq 'ngrok.exe' -and ($_.CommandLine -like '*frill-relay-nacho*' -or $_.CommandLine -like '*ngrok-siid.yml*') } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Start-Backend {
    Write-Log 'starting backend'
    Start-Process -FilePath $python -ArgumentList @('app.py') -WorkingDirectory $backendDir `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $tmp 'backend-output.log') `
        -RedirectStandardError  (Join-Path $tmp 'backend-error.log') | Out-Null
}

function Start-Ngrok {
    $ngrok = (Get-Command ngrok -ErrorAction SilentlyContinue).Source
    if (-not $ngrok) { Write-Log 'ngrok not found on PATH'; return }
    Write-Log 'starting ngrok (http for the card + https for browsers)'
    $defaultConfig = Join-Path $env:LOCALAPPDATA 'ngrok\ngrok.yml'
    $siidConfig    = Join-Path $root 'ngrok-siid.yml'
    Start-Process -FilePath $ngrok -ArgumentList @('start', '--all', "--config=`"$defaultConfig`"", "--config=`"$siidConfig`"", '--log=stdout') `
        -WorkingDirectory $root -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $tmp 'ngrok-output.log') `
        -RedirectStandardError  (Join-Path $tmp 'ngrok-error.log') | Out-Null
}

Write-Log "watchdog started (pid $PID)"
$lastBackendStart = [datetime]::MinValue
$lastNgrokStart   = [datetime]::MinValue
$wasHealthy       = $false

while (-not (Test-Path -LiteralPath $stopFlag)) {
    [SiidOnline.Power]::SetThreadExecutionState($keepAwake) | Out-Null

    $backendUp = Test-Url 'http://127.0.0.1:5000/readyz'
    if (-not $backendUp -and ((Get-Date) - $lastBackendStart).TotalSeconds -gt 45) {
        Stop-Backend
        Start-Backend
        $lastBackendStart = Get-Date
    }

    $tunnelUp = Test-Tunnel
    if (-not $tunnelUp -and ((Get-Date) - $lastNgrokStart).TotalSeconds -gt 45) {
        Stop-Ngrok
        Start-Ngrok
        $lastNgrokStart = Get-Date
    }

    $healthy = $backendUp -and $tunnelUp
    if ($healthy -ne $wasHealthy) {
        if ($healthy) { Write-Log "ONLINE: $publicUrl" } else { Write-Log "DOWN (backend=$backendUp, tunnel=$tunnelUp)" }
        $wasHealthy = $healthy
    }
    Start-Sleep -Seconds 15
}

Write-Log 'stop requested; shutting down backend and ngrok'
Stop-Backend
Stop-Ngrok
[SiidOnline.Power]::SetThreadExecutionState([uint32]2147483648) | Out-Null
Remove-Item -LiteralPath $pidFile, $stopFlag -ErrorAction SilentlyContinue
Write-Log 'watchdog stopped'
