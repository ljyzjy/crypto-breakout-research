<#
BtcTrendV4: long/short perp trend with a funding gate and a 1.0-1.75x ladder.

Examples:
  .\run-btc-trend-v4.ps1                     # backtest 2020-01 -> 2026-10
  .\run-btc-trend-v4.ps1 -Fee 0.0008         # double the taker fee
  .\run-btc-trend-v4.ps1 -Action lookahead   # look-ahead bias check
  .\run-btc-trend-v4.ps1 -Action paper       # dry-run trading
#>
param(
  [ValidateSet("backtest", "lookahead", "paper")] [string]$Action = "backtest",
  [string]$Timerange = "20200101-20261031",
  [double]$Fee = 0.0004,
  [string]$Strategy = "BtcTrendV4"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $here "..\..\work\freqtrade-env\Scripts\python.exe"
$cfg = @("--config", "config.btc-trend-v4.json", "--config", "config.v4-futures-data.json", "--userdir", "user_data")

Push-Location $here
try {
  switch ($Action) {
    "backtest" {
      & $py -m freqtrade backtesting @cfg --strategy $Strategy --timeframe 1d `
        --timerange $Timerange --fee $Fee --export trades
    }
    "lookahead" {
      & $py -m freqtrade lookahead-analysis @cfg --strategy $Strategy --timeframe 1d `
        --timerange 20210101-20250101
    }
    "paper" {
      Write-Host "NOTE: freqtrade does not simulate liquidation. Never raise LEV_MAX in the strategy file." -ForegroundColor Yellow
      & $py -m freqtrade trade @cfg --strategy $Strategy
    }
  }
}
finally { Pop-Location }
