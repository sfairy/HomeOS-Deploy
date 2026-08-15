"""部署进度解析与文本进度条。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# docker pull: Downloading [====>] 12.34MB/56.78MB
_SIZE_RE = re.compile(
    r"(?P<done>\d+(?:\.\d+)?)\s*(?P<du>kB|MB|GB|B)\s*/\s*"
    r"(?P<total>\d+(?:\.\d+)?)\s*(?P<tu>kB|MB|GB|B)",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_LAYER_RE = re.compile(r"^([0-9a-f]{8,64}|[a-z0-9][\w./:-]+):\s*(.+)$", re.IGNORECASE)

_UNIT = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


def _to_bytes(value: float, unit: str) -> float:
    return value * _UNIT.get(unit.upper(), 1)


def render_bar(percent: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, float(percent)))
    filled = int(round(width * pct / 100.0))
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:5.1f}%"


@dataclass
class DeployProgress:
    """综合阶段进度 + 从 docker 输出解析的拉取进度。"""

    phase: str = "idle"
    # 阶段权重：pull 占 0~80，up 占 80~100
    phase_base: float = 0.0
    phase_span: float = 100.0
    layer_ratio: dict[str, float] = field(default_factory=dict)
    last_percent: float = 0.0

    def set_phase(self, name: str, base: float, span: float) -> float:
        self.phase = name
        self.phase_base = base
        self.phase_span = span
        if name == "pull":
            self.layer_ratio.clear()
        return self._emit(0.0 if name != "up" else 0.0)

    def complete_phase(self) -> float:
        self.last_percent = self.phase_base + self.phase_span
        return self.last_percent

    def feed_line(self, line: str) -> float | None:
        """解析一行输出；有进度更新时返回新百分比，否则 None。"""
        text = line.strip()
        if not text:
            return None

        layer = None
        rest = text
        m_layer = _LAYER_RE.match(text)
        if m_layer:
            layer = m_layer.group(1)
            rest = m_layer.group(2)

        ratio: float | None = None
        m_size = _SIZE_RE.search(rest)
        if m_size:
            done = _to_bytes(float(m_size.group("done")), m_size.group("du"))
            total = _to_bytes(float(m_size.group("total")), m_size.group("tu"))
            if total > 0:
                ratio = max(0.0, min(1.0, done / total))

        if ratio is None:
            m_pct = _PCT_RE.search(rest)
            if m_pct:
                ratio = max(0.0, min(1.0, float(m_pct.group(1)) / 100.0))

        lower = rest.lower()
        if ratio is None and layer:
            if "pull complete" in lower or "already exists" in lower or "download complete" in lower:
                ratio = 1.0
            elif "waiting" in lower or "pulling fs layer" in lower:
                ratio = max(self.layer_ratio.get(layer, 0.0), 0.02)

        if ratio is not None and layer:
            prev = self.layer_ratio.get(layer, 0.0)
            if ratio >= prev:
                self.layer_ratio[layer] = ratio

        if self.phase == "pull" and self.layer_ratio:
            avg = sum(self.layer_ratio.values()) / len(self.layer_ratio)
            return self._emit(avg)

        if ratio is not None and self.phase != "pull":
            return self._emit(ratio)

        # 无法解析百分比时：pull 阶段给起步反馈，避免进度条长时间停在 0
        if self.phase == "pull" and text:
            local = (self.last_percent - self.phase_base) / max(self.phase_span, 1e-6)
            if local < 0.05:
                return self._emit(0.05)

        return None

    def _emit(self, local: float) -> float:
        local = max(0.0, min(1.0, local))
        pct = self.phase_base + self.phase_span * local
        # 进度只前进不回退（同阶段内）
        if pct < self.last_percent and self.phase == "pull":
            pct = self.last_percent
        self.last_percent = pct
        return pct

    def format_log(self, percent: float, detail: str = "") -> str:
        bar = render_bar(percent)
        phase = self.phase or "deploy"
        extra = f" | {detail}" if detail else ""
        return f"进度 {bar} ({phase}){extra}"
