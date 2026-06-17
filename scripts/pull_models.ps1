param(
  [ValidateSet("recommended", "low_resource", "high_end")]
  [string]$Profile = "recommended"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
  throw "Virtual environment not found. Run .\scripts\install_windows.ps1 first."
}

Push-Location $Root
try {
  & $VenvPython -m dumbo models pull --profile $Profile
}
finally {
  Pop-Location
}
