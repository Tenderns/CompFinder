param([string]$ModelSource = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv venv .venv --python 3.11
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the Python environment." }
}
if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv pip install --python $pythonPath -e "./backend[dev]"
} else {
    & $pythonPath -m pip install -e "./backend[dev]"
}
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
# -ModelSource is a folder holding model.onnx and model.onnx_data downloaded by hand.
if ($ModelSource) {
    & $pythonPath -m compfinder.model_setup --source $ModelSource
} else {
    & $pythonPath -m compfinder.model_setup
}
if ($LASTEXITCODE -ne 0) { throw "Model setup failed. Set HF_ENDPOINT=https://hf-mirror.com to use a mirror, or download the two files and pass -ModelSource <folder>." }
Push-Location (Join-Path $projectRoot "frontend")
try {
    & npm.cmd ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Frontend dependency installation failed." }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
} finally { Pop-Location }
Write-Host "Setup complete. Run .\scripts\start.ps1 and open http://127.0.0.1:8010"
