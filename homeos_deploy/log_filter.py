"""控制台输出过滤：去掉机器标记、sudo 提示与过密的层下载行。"""

from __future__ import annotations

import re

_NOISE_EXACT = {
    "COMPOSE_OK",
    "COMPOSE_MISSING",
    "WORKDIR_MISSING",
}

_NOISE_PREFIX = (
    "Could not chdir to home directory",
    "WORKDIR_MISSING:",
    "[sudo] password",
    "Sorry, try again",
    "password for",
)

# CSI / OSC 等 ANSI 控制序列。
# 不能用 raw string 写 \x1b：r"\x1b" 是四个字符，匹配不到 ESC，TUI 会原样漏到控制台。
_ANSI_RE = re.compile(
    "\x1b\\[[0-9;?]*[ -/]*[@-~]"
    "|\x9b[0-9;?]*[ -/]*[@-~]"
    "|\x1b\\][^\x07\x1b]*(?:\x07|\x1b\\\\)"
    "|\x1b[NO()][AB012]?"
    "|\x1b[=>]"
)

# 复制日志或拆包后 ESC 丢失，残留 [?25l [6A [0G [33m
_ORPHAN_CSI_RE = re.compile(
    r"\[\?\d+[A-Za-z]|\[\d+(?:;\d+)*[A-Za-z]"
)

# 仅过滤「层 hash」的高频刷屏；镜像名 / Pulling from 等仍显示
_LAYER_HASH_PROGRESS = re.compile(
    r"^[0-9a-f]{12,64}:\s*"
    r"(Waiting|Downloading|Extracting|Verifying Checksum|Pull complete|"
    r"Already exists|Download complete|Pulling fs layer)\b",
    re.IGNORECASE,
)

_DIGEST_ONLY = re.compile(r"^digest:\s*sha256:", re.IGNORECASE)

_COMPOSE_TTY_HEADER = re.compile(r"\[\+\]\s*\S+\s+\d+\s*/\s*\d+", re.I)

_COMPOSE_TTY_SPINNER = re.compile(r"[✔✘✓×●○⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]")

_BRAILLE_RE = re.compile(r"[\u2800-\u28FF]")

_COMPOSE_IMAGE_ERROR = re.compile(r"Image\s+\S+.*\bError\b", re.I)

_COMPOSE_IMAGE_STATUS = re.compile(
    r"Image\s+\S+.*\b(?:Pulling|Pulled|Waiting)\b",
    re.I,
)

_COMPOSE_TTY_SECONDS = re.compile(r"\d+\.\d+s\s*$")

# compose up 瞬时态：Waiting / Starting / 正常退出
_COMPOSE_UP_TRANSIENT = re.compile(
    r"^Container\s+\S+\s+(Waiting|Starting|Exited)\s*$",
    re.I,
)
_DEPLOY_INIT_EVENT = re.compile(r"^Container\s+\S*deploy-init\b", re.I)

_HEALTH_PROBE = re.compile(
    r"^--\s*exit=\d+\s*$"
    r"|^(PONG|/var/run/postgresql:\d+\s+-\s+accepting connections)\s*$",
    re.I,
)

_CONTAINER_EVENT = re.compile(
    r"^Container\s+(?P<name>\S+)\s+(?P<status>.+)$"
)
_STATUS_ZH = {
    "running": "运行中",
    "started": "已启动",
    "healthy": "健康",
    "recreate": "准备重建",
    "recreated": "已重建",
    "error": "失败",
}

_DUP_SUFFIX = re.compile(r"^(?P<base>.*)  \(×(?P<n>\d+)\)$")


def strip_ansi(text: str) -> str:
    if not text:
        return ""
    return _ANSI_RE.sub("", text)


def clean_log_text(line: str) -> str:
    """去掉 ANSI / 残留 CSI，得到可匹配的纯文本。"""
    text = strip_ansi(line or "")
    text = _ORPHAN_CSI_RE.sub("", text)
    return text.replace("\ufffd", "").strip()


def is_progress_log_line(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith("拉取 [") or t.startswith("进度 [")


def collapse_with_previous(previous: str | None, current: str) -> str | None:
    """当前行与上一行相同则返回应替换的「原文 (×N)」；否则 None。"""
    if not previous or not current:
        return None
    m = _DUP_SUFFIX.match(previous)
    base = m.group("base") if m else previous
    n = int(m.group("n")) if m else 1
    if current == base:
        return f"{base}  (×{n + 1})"
    return None


def format_console_line(line: str) -> str:
    """把 Compose 容器事件收成短中文行，其余原样。"""
    text = clean_log_text(line)
    if not text:
        return ""
    m = _CONTAINER_EVENT.match(text)
    if not m:
        return text
    name = m.group("name")
    status = m.group("status").strip()
    key = status.split()[0].lower()
    zh = _STATUS_ZH.get(key)
    if not zh:
        return text
    rest = status[len(status.split()[0]) :].strip()
    if rest:
        return f"{name}  {zh}  {rest}"
    return f"{name}  {zh}"


def _is_compose_tui_frame(text: str) -> bool:
    if _COMPOSE_TTY_HEADER.search(text):
        return True
    if _COMPOSE_IMAGE_ERROR.search(text):
        return False
    if "Image " not in text:
        return False
    if _COMPOSE_TTY_SPINNER.search(text) or _BRAILLE_RE.search(text):
        return True
    if _COMPOSE_IMAGE_STATUS.search(text):
        return True
    if _COMPOSE_TTY_SECONDS.search(text) and (
        " Pulling" in text or " Pulled" in text or " Waiting" in text
    ):
        return True
    return False


def should_show_log_line(line: str) -> bool:
    text = clean_log_text(line)
    if not text:
        return False
    if text in _NOISE_EXACT:
        return False
    lower = text.lower()
    for prefix in _NOISE_PREFIX:
        if text.startswith(prefix) or lower.startswith(prefix.lower()):
            return False
    if text in ("Password:", "password:"):
        return False
    if _LAYER_HASH_PROGRESS.match(text):
        return False
    if _DIGEST_ONLY.match(text):
        return False
    if _is_compose_tui_frame(text):
        return False
    if _COMPOSE_UP_TRANSIENT.match(text) or _DEPLOY_INIT_EVENT.match(text):
        return False
    if _HEALTH_PROBE.match(text):
        return False
    return True
