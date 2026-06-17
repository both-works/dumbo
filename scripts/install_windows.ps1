Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Python = Get-Command python -ErrorAction Stop

Push-Location $Root
try {
  Write-Host "Creating virtual environment in $Root\.venv"
  & $Python.Source -m venv (Join-Path $Root ".venv")

  $VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
  & $VenvPython -m pip install -U pip
  if ($LASTEXITCODE -ne 0) { throw "Failed to upgrade pip." }
  & $VenvPython -m pip install -e ".[dev]"
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Dumbo. Check network access and build backend hatchling."
  }

  Write-Host "Dumbo installed. Run:"
  Write-Host "  .\scripts\run_dumbo.ps1 doctor"
  Write-Host "Optional extras:"
  Write-Host '  .\.venv\Scripts\python.exe -m pip install -e ".[browser]"'
  Write-Host '  .\.venv\Scripts\python.exe -m pip install -e ".[desktop]"'
  Write-Host '  .\.venv\Scripts\python.exe -m pip install -e ".[voice]"'
}
finally {
  Pop-Location
}
