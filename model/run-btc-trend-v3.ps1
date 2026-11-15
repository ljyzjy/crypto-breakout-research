<#
    BtcTrendV3 runner. Leaves V1/V2 runners and their configs untouched.

    Examples:
      .\run-btc-trend-v3.ps1                       # backtest 2017-09..2026-11, fee 0.10%
      .\run-btc-trend-v3.ps1 -Fee 0.002            # double-fee stress
      .\run-btc-trend-v3.ps1 -Action lookahead     # look-ahead bias check
      .\run-btc-trend-v3.ps1 -Action paper         # dry-run paper trading
#>
param(
    [ValidateSet('backtest', 'lookahead', 'paper')]
    [string]$Action = 'backtest',
    [string]$Timerange = '20170901-20261101',
    [double]$Fee = 0.001
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '..\..\work\freqtrade-env\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'freqtrade env not found.' }

$previousDryRun = $env:FREQTRADE__DRY_RUN
$env:FREQTRADE__DRY_RUN = 'true'
try {
    Push-Location -LiteralPath $PSScriptRoot
    $common = @('--config', 'config.btc-trend-v3.json', '--config', 'config.public-data.json',
                '--userdir', 'user_data', '--strategy', 'BtcTrendV3', '--timeframe', '1d')
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
