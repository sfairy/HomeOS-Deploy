"""HomeOS Deploy 入口。"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_package_path() -> None:
    """支持直接 python homeos_deploy/main.py 与 PyInstaller 两种启动方式。"""
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parent.parent
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


def main() -> None:
    _ensure_package_path()
    from homeos_deploy.app_ui import run_app

    run_app()


if __name__ == "__main__":
    main()
