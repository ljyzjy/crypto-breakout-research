$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv from https://docs.astral.sh/uv/getting-started/installation/ first.'
}
uv venv --python 3.12 .venv
if ($LASTEXITCODE -ne 0) { throw 'Environment creation failed.' }
uv pip install --python .venv/Scripts/python.exe -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& .venv/Scripts/python.exe -m freqtrade --version
