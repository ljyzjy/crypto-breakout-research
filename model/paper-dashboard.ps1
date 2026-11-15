param([ValidateSet('start','stop','status')][string]$Action = 'start')
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = Join-Path $PSScriptRoot '../../work/freqtrade-env/Scripts/python.exe' }
$python = (Resolve-Path -LiteralPath $python).Path
$script = Join-Path $PSScriptRoot 'dashboard/app.py'
if ($Action -eq 'stop') { & $python $script --stop; exit $LASTEXITCODE }
try { $state = Invoke-RestMethod 'http://127.0.0.1:8765/api/state' -TimeoutSec 3 } catch { $state = $null }
if ($Action -eq 'status') {
    if ($state.app -eq 'momentum-paper-dashboard') { $state | Select-Object ok,strategy,dry_run,equity,pnl,closed_count,updated,error | Format-List }
    else { Write-Output 'Paper dashboard is not running.' }
    exit
}
if ($state.app -eq 'momentum-paper-dashboard') { Write-Output 'Already running: http://127.0.0.1:8765'; exit }
$conflict = Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python' -and $_.CommandLine -match 'freqtrade.*trade.*DailyMomentum' }
if ($conflict) { throw 'DailyMomentum is already running separately. Stop that instance before starting the dashboard.' }
if (Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8080,8765 }) { throw 'Port 8080 or 8765 is occupied.' }
$logs = Join-Path $PSScriptRoot 'user_data/logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
Start-Process -FilePath $python -ArgumentList @('"' + $script + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'dashboard.stdout.log') -RedirectStandardError (Join-Path $logs 'dashboard.stderr.log') | Out-Null
Write-Output 'Starting paper engine and dashboard: http://127.0.0.1:8765'
