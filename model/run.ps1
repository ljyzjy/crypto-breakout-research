param(
    [ValidateSet('version','validate','download','backtest','lookahead','recursive','paper')]
    [string]$Action = 'validate',
    [string]$Timerange = '20250101-20261101',
    [double]$Fee = 0.001,
    [ValidateSet('SpotTrendV1','DailyDonchian','DailyMA','DailyMomentum','DailyBollinger')]
    [string]$Strategy = 'SpotTrendV1',
    [switch]$Detail
)
$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $PSScriptRoot '../../work/freqtrade-env/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.ps1 first.' }
# This helper only supports research and simulated trading, even if an inherited
# process environment contains a live-trading setting.
$previousDryRun = $env:FREQTRADE__DRY_RUN
$env:FREQTRADE__DRY_RUN = 'true'
try {
    Push-Location -LiteralPath $PSScriptRoot
    # Freqtrade includes its stop timestamp. Convert the user-facing exclusive
    # date boundary to one second earlier so adjacent research windows do not overlap.
    if ($Timerange -match '^(\d{8})-(\d{8})$') {
        $rangeStart = [DateTimeOffset]::ParseExact($Matches[1], 'yyyyMMdd', [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal).ToUnixTimeSeconds()
        $rangeEnd = [DateTimeOffset]::ParseExact($Matches[2], 'yyyyMMdd', [cultureinfo]::InvariantCulture, [Globalization.DateTimeStyles]::AssumeUniversal).ToUnixTimeSeconds() - 1
        if ($rangeEnd -lt $rangeStart) { throw 'Timerange end must follow start.' }
        $Timerange = "$rangeStart-$rangeEnd"
    }
    $common = @('--config', 'config.paper.json', '--config', 'config.public-data.json', '--userdir', 'user_data')
    if ($Action -in @('backtest','lookahead','recursive','paper')) { $common += @('--strategy', $Strategy) }
    switch ($Action) {
        'version' { $arguments = @('--version') }
        'validate' { $arguments = @('list-strategies') + $common }
        'download' {
            $arguments = @('download-data') + $common + @('--timerange', $Timerange, '--timeframes', '1h')
            if ($Detail) { $arguments += '5m' }
        }
        'backtest' {
            $arguments = @('backtesting') + $common + @('--timerange', $Timerange,
                '--fee', $Fee.ToString([cultureinfo]::InvariantCulture), '--enable-protections',
                '--cache', 'none', '--export', 'trades', '--breakdown', 'month', 'year')
            if ($Detail) { $arguments += @('--timeframe-detail', '5m') }
        }
        'lookahead' {
            $arguments = @('lookahead-analysis') + $common + @('--timerange', $Timerange,
                '--minimum-trade-amount', '20', '--targeted-trade-amount', '100')
        }
        'recursive' {
            $startup = if ($Strategy -eq 'SpotTrendV1') { @('210','420','840') } else { @('1800','2160','2880') }
            $arguments = @('recursive-analysis') + $common + @('--timerange', $Timerange,
                '-p', 'BTC/USDT', '--startup-candle') + $startup
        }
        'paper' {
            New-Item -ItemType Directory -Force -Path 'user_data/logs' | Out-Null
            $suffix = if ($Strategy -eq 'SpotTrendV1') { '' } else { "-$Strategy" }
            $arguments = @('trade') + $common + @('--db-url', "sqlite:///user_data/paper$suffix.sqlite",
                '--logfile', "user_data/logs/paper$suffix.log")
        }
    }
    & $python -m freqtrade @arguments
    if ($LASTEXITCODE -ne 0) { throw "Freqtrade failed (exit $LASTEXITCODE)." }
} finally {
    Pop-Location
    $env:FREQTRADE__DRY_RUN = $previousDryRun
}
