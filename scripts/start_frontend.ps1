# Start the Vite dev server on 127.0.0.1:5173 (Windows PowerShell).
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\frontend")
if (-not (Test-Path "node_modules")) { npm install }
npm run dev
