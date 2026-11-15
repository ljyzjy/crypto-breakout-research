<#
    MajorsTrendV1 runner. Keeps the existing run.ps1 untouched.

    Examples:
      .\run-majors-trend.ps1                      # backtest 2023-01..2026-11, fee 0.10%
      .\run-majors-trend.ps1 -Fee 0.002           # double-fee stress
      .\run-majors-trend.ps1 -Action paper        # dry-run paper trading
#>
param(
    [ValidateSet('backtest', 'lookahead', 'paper')]
    [string]$Action = 'backtest',
    [string]$Timerange = '20230101-20261101',
    [double]$Fee = 0.001
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '..\..\work\freqtrade-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) { throw 'freqtrade env not found. Run setup.ps1 first.' }

$previousDryRun = $env:FREQTRADE__DRY_RUN
$env:FREQTRADE__DRY_RUN = 'true'
try {
    Push-Location -LiteralPath $PSScriptRoot
    $common = @('--config', 'config.majors-trend.json', '--config', 'config.public-data.json',
                '--userdir', 'user_data', '--strategy', 'MajorsTrendV1', '--timeframe', '1d')
    switch ($Action) {
        'backtest' {
            & $python -m freqtrade backtesting @common --timerange $Timerange --fee $Fee --export trades
        }
        'lookahead' {
            & $python -m freqtrade lookahead-analysis @common --timerange $Timerange --fee $Fee
        }
        'paper' {
            Write-Host 'Dry-run paper trading. Ctrl+C to stop. No real orders are sent.' -ForegroundColor Yellow
            & $python -m freqtrade trade @common
        }
    }
}
finally {
    $env:FREQTRADE__DRY_RUN = $previousDryRun
    Pop-Location
}
