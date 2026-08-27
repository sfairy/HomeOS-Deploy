#!/usr/bin/env bash
# HomeOS Deploy - macOS 打包（产物为 .app）
# 注意：PyInstaller 不支持交叉编译——exe 须在 Windows 上用 build.ps1 打，.app 须在 macOS 上打。
# 默认 onedir（启动快）；单文件：./build.sh --onefile
set -euo pipefail
cd "$(dirname "$0")"

ONEFILE=0
case "${1:-}" in
    --onefile|-OneFile) ONEFILE=1 ;;
    "") ;;
    *) echo "Usage: ./build.sh [--onefile]"; exit 2 ;;
esac

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python not found: $PYTHON (可用 PYTHON=/path/to/python3 ./build.sh 指定)" >&2
    exit 1
fi

echo "==> Creating venv..."
if [ ! -x ".venv/bin/python" ]; then
    "$PYTHON" -m venv .venv
fi
VPY=".venv/bin/python"

echo "==> Installing dependencies..."
"$VPY" -m pip install --upgrade pip
"$VPY" -m pip install -r requirements.txt   # pywin32 仅在 Windows 安装，macOS 自动跳过
"$VPY" -m pip install pyinstaller

echo "==> Preparing app icon..."
"$VPY" scripts/make_icon.py                  # app.ico + （darwin）app.icns
ICNS="homeos_deploy/assets/app.icns"
if [ ! -f "$ICNS" ]; then
    echo "App icon missing: $ICNS" >&2
    exit 1
fi

BUNDLE=(--onedir)
[ "$ONEFILE" = "1" ] && BUNDLE=(--onefile)

echo "==> Building HomeOS-Deploy (macOS ${BUNDLE[0]})..."
"$VPY" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --noupx \
    "${BUNDLE[@]}" \
    --name "HomeOS-Deploy" \
    --icon "$ICNS" \
    --paths "." \
    --add-data "homeos_deploy/assets/app.png:homeos_deploy/assets" \
    --hidden-import=paramiko \
    --hidden-import=customtkinter \
    --hidden-import=homeos_deploy.ui \
    --hidden-import=homeos_deploy.ui.app \
    --hidden-import=homeos_deploy.ui.steps \
    --hidden-import=homeos_deploy.ui.sidebar \
    --hidden-import=homeos_deploy.ui.console \
    --hidden-import=homeos_deploy.ui.action_bar \
    --hidden-import=homeos_deploy.ui.components \
    --hidden-import=homeos_deploy.ui.constants \
    --hidden-import=homeos_deploy.log_filter \
    --hidden-import=homeos_deploy.app_controller \
    --collect-submodules homeos_deploy \
    --collect-all customtkinter \
    --collect-all paramiko \
    "homeos_deploy/main.py"

APP="dist/HomeOS-Deploy.app"
echo ""
if [ "$ONEFILE" = "1" ]; then
    echo "Done: $(pwd)/dist/HomeOS-Deploy (unix 可执行文件)"
else
    echo "Done: $(pwd)/$APP"
    echo "分发请拷贝整个 .app；接收方首次打开需右键 → 打开（绕过 Gatekeeper）。"
fi
