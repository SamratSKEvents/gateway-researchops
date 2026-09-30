# One-command start: ResearchOps on http://localhost:<port>.
#   powershell -ExecutionPolicy Bypass -File run.ps1              # port 8765, or the next free port
# Ollama + SearXNG live in WSL on this laptop. They are only started if not already answering, with a hard timeout.
param([int]$Port = 8765)
Set-Location $PSScriptRoot
[Console]::OutputEncoding = [Text.Encoding]::UTF8; $env:PYTHONIOENCODING = "utf-8"
if (-not $env:LLM_BASE_URL) { $env:LLM_BASE_URL = "http://localhost:11434/v1" }
if (-not $env:LLM_MODEL) { $env:LLM_MODEL = "qwen3:4b" }

function Up($url) { try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 2 | Out-Null; $true } catch { $false } }

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { Write-Host "uv not found - install from https://docs.astral.sh/uv/" -ForegroundColor Red; exit 1 }

$keep = $null
if (-not ((Up "http://localhost:11434/api/tags") -and (Up "http://localhost:9090"))) {
    Write-Host "Starting Ollama + SearXNG in WSL (max 60 s)..."
    $keep = Start-Process wsl -ArgumentList "-e","sleep","infinity" -WindowStyle Hidden -PassThru -ErrorAction SilentlyContinue
    $job = Start-Job { wsl -u root -e sh -c "systemctl start ollama; docker start searxng-valkey searxng-core" }
    if (-not (Wait-Job $job -Timeout 60)) { Write-Host "WSL did not answer in 60 s - continuing without it." -ForegroundColor Yellow }
    Remove-Job $job -Force
    foreach ($i in 1..10) { if (Up "http://localhost:11434/api/tags") { break }; Start-Sleep 2 }
}

while (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { $Port++ }

uv sync --quiet
Write-Host "`nResearchOps -> http://localhost:$Port/" -ForegroundColor Green
Start-Job { Start-Sleep 4; Start-Process "http://localhost:$using:Port/" } | Out-Null
try { uv run uvicorn backend.app:app --port $Port } finally { if ($keep) { Stop-Process -Id $keep.Id -ErrorAction SilentlyContinue } }
