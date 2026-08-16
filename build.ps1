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

Write-Host "==> Preparing app icon..."
& .\.venv\Scripts\python.exe scripts\make_icon.py
$icon = Join-Path $PSScriptRoot "homeos_deploy\assets\app.ico"
if (-not (Test-Path $icon)) {
    throw "App icon missing: $icon"
}

Write-Host "==> Building HomeOS-Deploy.exe..."
& .\.venv\Scripts\python.exe -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name "HomeOS-Deploy" `
    --icon $icon `
    --paths "." `
    --add-data "homeos_deploy\assets\app.ico;homeos_deploy\assets" `
    --add-data "homeos_deploy\assets\app.png;homeos_deploy\assets" `
    --hidden-import=paramiko `
    --hidden-import=customtkinter `
    --hidden-import=win32crypt `
    --hidden-import=win32clipboard `
    --hidden-import=homeos_deploy.ui `
    --hidden-import=homeos_deploy.ui.app `
    --hidden-import=homeos_deploy.ui.steps `
    --hidden-import=homeos_deploy.ui.sidebar `
    --hidden-import=homeos_deploy.ui.console `
    --hidden-import=homeos_deploy.ui.action_bar `
    --hidden-import=homeos_deploy.ui.components `
    --hidden-import=homeos_deploy.ui.constants `
    --hidden-import=homeos_deploy.log_filter `
    --hidden-import=homeos_deploy.app_controller `
    --collect-submodules homeos_deploy `
    --collect-all customtkinter `
    --collect-all paramiko `
    "homeos_deploy\main.py"

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done: $PSScriptRoot\dist\HomeOS-Deploy.exe"
