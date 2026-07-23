# Launch the MCP Server Builder: FastAPI backend + Streamlit frontend.
# Usage:  ./run.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "Starting FastAPI backend on http://localhost:8000 ..." -ForegroundColor Cyan
$api = Start-Process -PassThru -WorkingDirectory $root powershell -ArgumentList `
    '-NoExit', '-Command', 'uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload'

Start-Sleep -Seconds 2

Write-Host "Starting Streamlit frontend on http://localhost:8501 ..." -ForegroundColor Cyan
$env:MCP_API_URL = "http://localhost:8000"
streamlit run frontend/app.py
