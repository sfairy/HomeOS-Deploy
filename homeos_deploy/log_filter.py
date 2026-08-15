"""控制台输出过滤：去掉机器标记、sudo 提示与 docker 层进度噪音。"""

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

# docker pull 按层刷进度；进度条已解析，控制台不必逐条显示
_LAYER_PROGRESS = re.compile(
    r"^[0-9a-f]{8,64}:\s*"
    r"(Waiting|Downloading|Extracting|Verifying Checksum|Pull complete|"
    r"Already exists|Download complete|Pulling fs layer|Extracting|"
    r"Pulling|Waiting)\b",
    re.IGNORECASE,
)

_DIGEST_ONLY = re.compile(r"^digest:\s*sha256:", re.IGNORECASE)


def should_show_log_line(line: str) -> bool:
    text = (line or "").strip()
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
    if _LAYER_PROGRESS.match(text):
        return False
    if _DIGEST_ONLY.match(text):
        return False
    return True
