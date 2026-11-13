$ErrorActionPreference = 'Stop'
$statePath = Join-Path $PSScriptRoot 'tmp\demo-processes.json'

if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host 'No launcher-owned demo processes were recorded.'
    exit 0
}

$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$targets = @(
    @{ Name = 'backend'; Id = $state.backend_pid; StartTicks = $state.backend_start_ticks },
    @{ Name = 'ngrok'; Id = $state.ngrok_pid; StartTicks = $state.ngrok_start_ticks }
)
foreach ($target in $targets) {
    if ($null -eq $target.Id) { continue }
    $process = Get-Process -Id $target.Id -ErrorAction SilentlyContinue
    if ($process -and $target.StartTicks -and $process.StartTime.Ticks -eq $target.StartTicks) {
        Stop-Process -Id $target.Id
        Write-Host "Stopped $($process.ProcessName) (PID $($target.Id))."
    } elseif ($process) {
        Write-Warning "Skipped PID $($target.Id): it no longer matches the launcher record."
    }
}
Remove-Item -LiteralPath $statePath
