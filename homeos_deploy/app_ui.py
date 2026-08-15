"""兼容入口：转发到 ui.app。"""

from homeos_deploy.ui.app import HomeOSDeployApp, run_app

__all__ = ["HomeOSDeployApp", "run_app"]
