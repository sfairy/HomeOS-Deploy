"""资源路径：源码运行与 PyInstaller 打包共用。"""

from __future__ import annotations

import sys
from pathlib import Path


def package_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "homeos_deploy"
    return Path(__file__).resolve().parent


def asset_path(*parts: str) -> Path:
    return package_dir().joinpath("assets", *parts)
