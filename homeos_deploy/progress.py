"""部署进度：总体阶段 + 拉取镜像子进度（只前进不回退）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from homeos_deploy.log_filter import clean_log_text

# —— 全局阶段区间（百分比）——
# 准备 0~5，拉取 5~85，启动 85~100
PHASE_PREPARE_END = 5.0
PHASE_PULL_BASE = 5.0
PHASE_PULL_SPAN = 80.0
PHASE_UP_BASE = 85.0
PHASE_UP_SPAN = 15.0

_SIZE_RE = re.compile(
    r"(?P<done>\d+(?:\.\d+)?)\s*(?P<du>kB|MB|GB|B)\s*/\s*"
    r"(?P<total>\d+(?:\.\d+)?)\s*(?P<tu>kB|MB|GB|B)",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
_LAYER_RE = re.compile(
    r"^(?P<id>[0-9a-f]{12,64}|[a-z0-9][\w./:-]*?):\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_BUILDKIT_RE = re.compile(r"^#(?P<n>\d+)\s+(?P<rest>.+)$")

_COMPOSE_COUNT_RE = re.compile(
    r"\[\+\]\s*pull\s+(?P<done>\d+)\s*/\s*(?P<total>\d+)",
    re.I,
)
_COMPOSE_IMAGE_RE = re.compile(
    r"Image\s+(?P<name>\S+)\s+"
    r"(?:\[(?P<bar>[\u2800-\u28FF]+)\]\s*)?"
    r"(?P<status>Pulled|Pulling|Waiting|Error)",
    re.I,
)

_BRAILLE_PARTIAL = {
    "⡀": 1 / 8,
    "⣀": 2 / 8,
    "⣄": 3 / 8,
    "⣤": 4 / 8,
    "⣦": 5 / 8,
    "⣶": 6 / 8,
    "⣷": 7 / 8,
}

_UNIT = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


def _braille_ratio(bar: str) -> float:
    if not bar:
        return 0.05
    n = len(bar)
    last = bar[-1]
    if last == "⣿":
        return max(0.02, min(0.99, bar.count("⣿") / n))
    partial = _BRAILLE_PARTIAL.get(last, 0.4)
    filled = bar[:-1].count("⣿")
    return max(0.02, min(0.99, (filled + partial) / n))


def _to_bytes(value: float, unit: str) -> float:
    return value * _UNIT.get(unit.upper(), 1)


def render_bar(percent: float, width: int = 20) -> str:
    pct = max(0.0, min(100.0, float(percent)))
    filled = int(round(width * pct / 100.0))
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:3.0f}%"


@dataclass
class DeployProgress:
    """总体部署进度 + 拉取阶段本地进度。"""

    phase: str = "idle"
    phase_base: float = 0.0
    phase_span: float = 100.0
    layer_ratio: dict[str, float] = field(default_factory=dict)
    layer_weight: dict[str, float] = field(default_factory=dict)
    last_percent: float = 0.0
    last_pull_percent: float = 0.0  # 拉取子进度 0~100
    activity_lines: int = 0
    compose_done: int = 0
    compose_total: int = 0

    def set_phase(self, name: str, base: float, span: float) -> float:
        self.phase = name
        self.phase_base = float(base)
        self.phase_span = float(span)
        self.activity_lines = 0
        if name == "pull":
            self.layer_ratio.clear()
            self.layer_weight.clear()
            self.last_pull_percent = 0.0
            self.compose_done = 0
            self.compose_total = 0
        return self._commit(self.phase_base)

    def complete_phase(self) -> float:
        if self.phase == "pull":
            self.last_pull_percent = 100.0
        return self._commit(self.phase_base + self.phase_span)

    @property
    def layer_stats(self) -> tuple[int, int]:
        """返回 (已完成层数, 已见层数)。"""
        total = len(self.layer_ratio)
        done = sum(1 for r in self.layer_ratio.values() if r >= 0.999)
        return done, total

    def feed_line(self, line: str) -> float | None:
        text = clean_log_text(line)
        if not text:
            return None

        self.activity_lines += 1

        if self.phase == "pull":
            local = self._pull_local(text)
            local = min(local, 0.96)
            self.last_pull_percent = max(self.last_pull_percent, local * 100.0)
            return self._commit(self.phase_base + self.phase_span * local)

        if self.phase == "up":
            self.last_pull_percent = 100.0
            local = self._up_local(text)
            local = min(local, 0.90)
            return self._commit(self.phase_base + self.phase_span * local)

        return None

    def format_pull_log(self, overall: float) -> str:
        """控制台专用：拉取子进度条。"""
        bar = render_bar(self.last_pull_percent, width=18)
        parts: list[str] = []
        if self.compose_total:
            parts.append(f"镜像 {self.compose_done}/{self.compose_total}")
        else:
            img_keys = [k for k in self.layer_ratio if k.startswith("img:")]
            if img_keys:
                img_done = sum(1 for k in img_keys if self.layer_ratio[k] >= 0.999)
                parts.append(f"镜像 {img_done}/{len(img_keys)}")
        hash_keys = [
            k
            for k in self.layer_ratio
            if not k.startswith("img:") and not k.startswith("bk:")
        ]
        if hash_keys:
            h_done = sum(1 for k in hash_keys if self.layer_ratio[k] >= 0.999)
            parts.append(f"层 {h_done}/{len(hash_keys)}")
        extra = (" · " + " · ".join(parts)) if parts else ""
        return f"拉取 {bar}{extra} · 总体 {overall:3.0f}%"

    def format_log(self, percent: float, detail: str = "") -> str:
        if self.phase == "pull":
            return self.format_pull_log(percent)
        bar = render_bar(percent)
        labels = {
            "idle": "待命",
            "prepare": "准备",
            "pull": "拉取镜像",
            "up": "启动容器",
            "deploy": "部署",
        }
        phase = labels.get(self.phase or "deploy", self.phase or "部署")
        extra = ""
        if detail and detail not in (phase, "拉取镜像", "启动容器"):
            extra = f" | {detail}"
        return f"进度 {bar} ({phase}){extra}"

    def _pull_local(self, text: str) -> float:
        m_count = _COMPOSE_COUNT_RE.search(text)
        if m_count:
            done = int(m_count.group("done"))
            total = max(int(m_count.group("total")), 1)
            # TUI 重绘可能短暂回退，计数只升不降
            self.compose_total = max(self.compose_total, total)
            self.compose_done = max(self.compose_done, min(done, self.compose_total))

        m_img = _COMPOSE_IMAGE_RE.search(text)
        if m_img:
            name = m_img.group("name").rstrip(":")
            status = m_img.group("status").lower()
            bar = m_img.group("bar") or ""
            key = f"img:{name}"
            if status == "pulled":
                ratio = 1.0
            elif bar:
                ratio = _braille_ratio(bar)
            else:
                ratio = max(self.layer_ratio.get(key, 0.0), 0.05)
            prev = self.layer_ratio.get(key, 0.0)
            if ratio >= prev:
                self.layer_ratio[key] = ratio

        layer_id, rest = self._split_layer(text)
        ratio, total_bytes = self._parse_ratio(rest)
        lower = rest.lower()

        if ratio is None and layer_id:
            if any(
                h in lower
                for h in ("pull complete", "already exists", "download complete")
            ):
                ratio = 1.0
            elif any(h in lower for h in ("waiting", "pulling fs layer")):
                ratio = max(self.layer_ratio.get(layer_id, 0.0), 0.02)
            elif "downloading" in lower or "extracting" in lower:
                ratio = max(self.layer_ratio.get(layer_id, 0.0), 0.1)

        if layer_id and ratio is not None:
            prev = self.layer_ratio.get(layer_id, 0.0)
            if ratio >= prev:
                self.layer_ratio[layer_id] = ratio
            if total_bytes and total_bytes > 0:
                self.layer_weight[layer_id] = max(
                    self.layer_weight.get(layer_id, 0.0), total_bytes
                )

        if "pulling from" in lower or "pulling fs layer" in lower:
            key = layer_id or f"img:{self.activity_lines}"
            self.layer_ratio.setdefault(key, 0.02)

        if any(
            h in lower for h in ("downloaded newer image", "image is up to date")
        ):
            if self.layer_ratio:
                for k, v in list(self.layer_ratio.items()):
                    if v < 1.0:
                        self.layer_ratio[k] = max(v, 0.99)
            else:
                self.layer_ratio["image-done"] = 1.0

        layer_avg = self._weighted_avg() if self.layer_ratio else None
        compose_avg = None
        if self.compose_total > 0:
            # 32/34 只计已完成；把视口里仍在拉的镜像按盲文条折进分子
            partial = sum(
                r
                for k, r in self.layer_ratio.items()
                if k.startswith("img:") and r < 0.999
            )
            compose_avg = (self.compose_done + partial) / self.compose_total
            if self.compose_done < self.compose_total:
                compose_avg = min(compose_avg, 0.99)

        if layer_avg is not None and compose_avg is not None:
            return max(layer_avg, compose_avg)
        if layer_avg is not None:
            return layer_avg
        if compose_avg is not None:
            return compose_avg
        return min(0.04 + self.activity_lines * 0.004, 0.40)

    def _up_local(self, text: str) -> float:
        lower = text.lower()
        bump = min(0.08 + self.activity_lines * 0.05, 0.85)
        if "started" in lower or "running" in lower:
            bump = max(bump, 0.75)
        elif "created" in lower or "recreat" in lower:
            bump = max(bump, 0.45)
        elif "building" in lower or "pulling" in lower:
            bump = max(bump, 0.25)
        return bump

    def _weighted_avg(self) -> float:
        total_w = 0.0
        acc = 0.0
        for layer, ratio in self.layer_ratio.items():
            w = self.layer_weight.get(layer, 1.0)
            if w <= 1.0:
                w = 1.0
            total_w += w
            acc += max(0.0, min(1.0, ratio)) * w
        if total_w <= 0:
            return 0.0
        avg = acc / total_w
        n = max(len(self.layer_ratio), 1)
        reserve = max(0.06, min(0.40, 0.45 / n))
        if any(r < 0.999 for r in self.layer_ratio.values()):
            avg = min(avg, 1.0 - reserve)
        else:
            avg = min(avg, 1.0 - reserve * 0.5)
        return max(0.0, min(1.0, avg))

    def _split_layer(self, text: str) -> tuple[str | None, str]:
        m = _BUILDKIT_RE.match(text)
        if m:
            return f"bk:{m.group('n')}", m.group("rest")
        m = _LAYER_RE.match(text)
        if m:
            return m.group("id"), m.group("rest")
        return None, text

    def _parse_ratio(self, rest: str) -> tuple[float | None, float | None]:
        ratio: float | None = None
        total_bytes: float | None = None
        m_size = _SIZE_RE.search(rest)
        if m_size:
            done = _to_bytes(float(m_size.group("done")), m_size.group("du"))
            total = _to_bytes(float(m_size.group("total")), m_size.group("tu"))
            if total > 0:
                ratio = max(0.0, min(1.0, done / total))
                total_bytes = total
        if ratio is None:
            m_pct = _PCT_RE.search(rest)
            if m_pct:
                ratio = max(0.0, min(1.0, float(m_pct.group(1)) / 100.0))
        return ratio, total_bytes

    def _commit(self, pct: float) -> float:
        pct = max(0.0, min(100.0, float(pct)))
        if pct < self.last_percent:
            pct = self.last_percent
        self.last_percent = pct
        return pct
