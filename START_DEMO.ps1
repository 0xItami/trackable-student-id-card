param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'

$projectRoot = $PSScriptRoot
$backendRoot = Join-Path $projectRoot 'backend'
$pythonPath = Join-Path $backendRoot 'venv\Scripts\python.exe'
$stateRoot = Join-Path $projectRoot 'tmp'
$statePath = Join-Path $stateRoot 'demo-processes.json'

function Test-DemoUrl([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 1
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "The Python environment is missing at $pythonPath"
}
New-Item -ItemType Directory -Path $stateRoot -Force | Out-Null
$previousState = $null
if (Test-Path -LiteralPath $statePath) {
    try { $previousState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } catch { }
}

function Get-RecordedProcess($RecordedPid, $RecordedStartTicks) {
    if (-not $RecordedPid -or -not $RecordedStartTicks) { return $null }
    $process = Get-Process -Id $RecordedPid -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.Ticks -eq [int64]$RecordedStartTicks) {
        return $process
    }
    return $null
}

function Save-DemoState($BackendPid, $BackendStartTicks, $NgrokPid, $NgrokStartTicks) {
    [ordered]@{
        started_at = (Get-Date).ToString('o')
        backend_pid = $BackendPid
        backend_start_ticks = $BackendStartTicks
        ngrok_pid = $NgrokPid
        ngrok_start_ticks = $NgrokStartTicks
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
}

$recordedBackend = if ($previousState) {
    Get-RecordedProcess $previousState.backend_pid $previousState.backend_start_ticks
} else { $null }
$recordedNgrok = if ($previousState) {
    Get-RecordedProcess $previousState.ngrok_pid $previousState.ngrok_start_ticks
} else { $null }
$backendPid = if ($recordedBackend) { $recordedBackend.Id } else { $null }
$backendStartTicks = if ($recordedBackend) { $recordedBackend.StartTime.Ticks } else { $null }
$ngrokPid = if ($recordedNgrok) { $recordedNgrok.Id } else { $null }
$ngrokStartTicks = if ($recordedNgrok) { $recordedNgrok.StartTime.Ticks } else { $null }

$backendProcess = $null
if (-not (Test-DemoUrl 'http://127.0.0.1:5000/readyz')) {
    Write-Host 'Starting the ABU tracking dashboard...'
    $backendProcess = Start-Process -FilePath $pythonPath `
        -ArgumentList @('app.py') `
        -WorkingDirectory $backendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $stateRoot 'backend-output.log') `
        -RedirectStandardError (Join-Path $stateRoot 'backend-error.log') `
        -PassThru

    $backendPid = $backendProcess.Id
    $backendStartTicks = $backendProcess.StartTime.Ticks
    Save-DemoState $backendPid $backendStartTicks $ngrokPid $ngrokStartTicks

    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline -and -not (Test-DemoUrl 'http://127.0.0.1:5000/readyz')) {
        Start-Sleep -Milliseconds 400
    }
    if (-not (Test-DemoUrl 'http://127.0.0.1:5000/readyz')) {
        throw "The dashboard did not start. Check tmp\backend-error.log."
    }
} else {
    Write-Host 'Dashboard is already running.'
}

$ngrokProcess = $null
if (-not (Test-DemoUrl 'http://127.0.0.1:4040/api/tunnels')) {
    $ngrokCommand = Get-Command ngrok -ErrorAction SilentlyContinue
    if ($ngrokCommand) {
        Write-Host 'Starting the public ngrok link for the LilyGO card...'
        try {
            $ngrokProcess = Start-Process -FilePath $ngrokCommand.Source `
                -ArgumentList @('http', '--url=http://frill-relay-nacho.ngrok-free.dev', '5000') `
                -WorkingDirectory $projectRoot `
                -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $stateRoot 'ngrok-output.log') `
                -RedirectStandardError (Join-Path $stateRoot 'ngrok-error.log') `
                -PassThru
            $ngrokPid = $ngrokProcess.Id
            $ngrokStartTicks = $ngrokProcess.StartTime.Ticks
            Save-DemoState $backendPid $backendStartTicks $ngrokPid $ngrokStartTicks

            $deadline = (Get-Date).AddSeconds(15)
            while ((Get-Date) -lt $deadline -and -not (Test-DemoUrl 'http://127.0.0.1:4040/api/tunnels')) {
                Start-Sleep -Milliseconds 500
            }
            if (-not (Test-DemoUrl 'http://127.0.0.1:4040/api/tunnels')) {
                Write-Warning 'ngrok started but its local status page did not become ready.'
            }
        } catch {
            Write-Warning "ngrok could not start: $($_.Exception.Message)"
        }
    } else {
        Write-Warning 'ngrok was not found. The saved/offline demonstration still works.'
    }
} else {
    Write-Host 'ngrok is already running.'
}

Save-DemoState $backendPid $backendStartTicks $ngrokPid $ngrokStartTicks

Write-Host ''
Write-Host 'Demo services are ready.' -ForegroundColor Green
Write-Host 'Login: admin / abu2026'
if (-not $NoBrowser) {
    Write-Host 'The browser will open the full readiness screen.'
    Start-Process 'http://127.0.0.1:5000/login?next=/health'
} else {
    Write-Host 'Readiness screen: http://127.0.0.1:5000/health'
}
