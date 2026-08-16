"""配置读写；本地用 DPAPI 加密，导入/导出支持可移植 JSON。"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from homeos_deploy.defaults import CONFIG_DIR_NAME, CONFIG_FILE_NAME

try:
    import win32crypt
except ImportError:  # pragma: no cover - non-Windows fallback for lint
    win32crypt = None  # type: ignore

CONFIG_FORMAT_VERSION = 1


@dataclass
class AppConfig:
    """首次运行全部为空，需手动填写或导入配置。"""

    host: str = ""
    port: int = 0  # 0 表示未设置
    user: str = ""
    workdir: str = ""
    ghcr_user: str = ""
    ssh_password: str = ""
    ghcr_token: str = ""
    last_service: str = ""
    down_before_deploy: bool = False  # 部署前先 compose down
    down_remove_volumes: bool = False  # down 时加 -v 删除数据卷

    def public_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port if self.port > 0 else "",
            "user": self.user,
            "workdir": self.workdir,
            "ghcr_user": self.ghcr_user,
            "last_service": self.last_service,
            "down_before_deploy": self.down_before_deploy,
            "down_remove_volumes": self.down_remove_volumes,
        }

    def is_empty(self) -> bool:
        return not any(
            [
                self.host,
                self.port,
                self.user,
                self.workdir,
                self.ghcr_user,
                self.ssh_password,
                self.ghcr_token,
                self.last_service,
            ]
        )


def resolve_sudo_password(cfg: AppConfig) -> str:
    """远程 docker 命令用 SSH 登录密码走 sudo。"""
    return cfg.ssh_password


def config_path() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return base / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _protect(plain: str) -> str:
    if not plain:
        return ""
    if win32crypt is None:
        return base64.b64encode(plain.encode("utf-8")).decode("ascii")
    encrypted = win32crypt.CryptProtectData(plain.encode("utf-8"), None, None, None, None, 0)
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect(blob: str) -> str:
    if not blob:
        return ""
    raw = base64.b64decode(blob.encode("ascii"))
    if win32crypt is None:
        return raw.decode("utf-8")
    _desc, decrypted = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
    return decrypted.decode("utf-8")


def _read_secret(data: dict[str, Any], plain_key: str, enc_key: str) -> str:
    """优先明文（可移植导出），否则尝试 DPAPI 密文（本机配置）。"""
    plain = data.get(plain_key)
    if isinstance(plain, str) and plain:
        return plain
    enc = data.get(enc_key)
    if isinstance(enc, str) and enc:
        try:
            return _unprotect(enc)
        except Exception:
            return ""
    return ""


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_flag(value: Any, default: bool = False) -> bool:
    """可选开关：仅认 bool，缺省用 default。"""
    if isinstance(value, bool):
        return value
    return default


def _as_port(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        port = int(value)
    except (TypeError, ValueError):
        return 0
    return port if 1 <= port <= 65535 else 0


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    return AppConfig(
        host=_as_str(data.get("host", "")),
        port=_as_port(data.get("port", 0)),
        user=_as_str(data.get("user", "")),
        workdir=_as_str(data.get("workdir", "")),
        ghcr_user=_as_str(data.get("ghcr_user", "")),
        ssh_password=_read_secret(data, "ssh_password", "ssh_password_enc"),
        ghcr_token=_read_secret(data, "ghcr_token", "ghcr_token_enc"),
        last_service=_as_str(data.get("last_service", "")),
        down_before_deploy=_as_flag(data.get("down_before_deploy"), False),
        down_remove_volumes=_as_flag(data.get("down_remove_volumes"), False),
    )


def load_config_file(path: Path | str) -> AppConfig:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件格式无效：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是对象。")
    return config_from_dict(data)


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    try:
        return load_config_file(path)
    except (OSError, ValueError, FileNotFoundError):
        return AppConfig()


def save_config(cfg: AppConfig, path: Path | str | None = None) -> Path:
    """写入本机配置（敏感字段 DPAPI 加密）。默认写到 %APPDATA%。"""
    target = Path(path) if path is not None else config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "homeos-deploy-local",
        "version": CONFIG_FORMAT_VERSION,
        **cfg.public_dict(),
        "ssh_password_enc": _protect(cfg.ssh_password),
        "ghcr_token_enc": _protect(cfg.ghcr_token),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def export_config(cfg: AppConfig, path: Path | str, include_secrets: bool = True) -> Path:
    """
    导出可移植配置文件（JSON）。
    include_secrets=True 时写入明文密码/Token，便于换机导入；请妥善保管该文件。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "format": "homeos-deploy-portable",
        "version": CONFIG_FORMAT_VERSION,
        **cfg.public_dict(),
    }
    if include_secrets:
        payload["ssh_password"] = cfg.ssh_password
        payload["ghcr_token"] = cfg.ghcr_token
    else:
        payload["ssh_password"] = ""
        payload["ghcr_token"] = ""
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def import_config(path: Path | str, apply_locally: bool = True) -> AppConfig:
    """从任意路径导入配置；可选立即写入本机默认配置文件。"""
    cfg = load_config_file(path)
    if apply_locally:
        save_config(cfg)
    return cfg


def clear_secrets(cfg: AppConfig) -> AppConfig:
    cfg.ssh_password = ""
    cfg.ghcr_token = ""
    save_config(cfg)
    return cfg
