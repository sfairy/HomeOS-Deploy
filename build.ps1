# HomeOS Deploy - 一键打包 Windows exe
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Creating venv..."
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

Write-Host "==> Installing dependencies..."
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip install pyinstaller

Write-Host "==> Building HomeOS-Deploy.exe..."
& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name "HomeOS-Deploy" `
    --paths "." `
    --hidden-import=paramiko `
    --hidden-import=customtkinter `
    --hidden-import=win32crypt `
    --collect-all customtkinter `
    --collect-all paramiko `
    "homeos_deploy\main.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done: $PSScriptRoot\dist\HomeOS-Deploy.exe"
