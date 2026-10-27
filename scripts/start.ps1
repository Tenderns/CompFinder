param([int]$Port = 8010, [switch]$Public)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "Run .\scripts\setup.ps1 first." }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "frontend\dist\index.html"))) { throw "Frontend is not built. Run .\scripts\setup.ps1 first." }
Set-Location -LiteralPath $projectRoot
# -Public listens on every network interface; otherwise only this computer can connect.
$listen = if ($Public) { "0.0.0.0" } else { "127.0.0.1" }
$dataDir = if ($env:COMPFINDER_DATA_DIR) { $env:COMPFINDER_DATA_DIR } else { Join-Path $projectRoot "data" }
# Creates data\access-token.txt on first run unless COMPFINDER_TOKEN is set.
& $pythonPath -c "from compfinder.config import Settings; Settings.from_env()"
if ($LASTEXITCODE -ne 0) { throw "Access token setup failed." }
$tokenFile = Join-Path $dataDir "access-token.txt"
$token = if ($env:COMPFINDER_TOKEN) { $env:COMPFINDER_TOKEN } else { (Get-Content -LiteralPath $tokenFile -Raw).Trim() }
Write-Host "CompFinder: http://127.0.0.1:$Port"
if ($Public) {
    Write-Host "Listening on all interfaces (port $Port). Put HTTPS in front before exposing it to the internet; plain HTTP sends the token in clear text." -ForegroundColor Yellow
}
Write-Host "Web login token: $token"
Write-Host "MCP endpoint: /mcp  (create MCP tokens in the web page, tab AI)"
Write-Host "Keep this terminal open. Press Ctrl+C to stop."
& $pythonPath -m uvicorn compfinder.api:app --host $listen --port $Port
exit $LASTEXITCODE
