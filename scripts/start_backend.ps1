# Start the FastAPI backend on 127.0.0.1:8000 (Windows PowerShell). PAPER TRADING ONLY.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")
if (-not (Test-Path ".venv")) {
  py -3 -m venv .venv
  .\.venv\Scripts\pip.exe install -r requirements.txt
}
.\.venv\Scripts\python.exe run.py
