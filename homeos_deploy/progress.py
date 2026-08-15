"""部署进度：阶段权重 + docker 输出解析（只前进不回退）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# —— 全局阶段区间（百分比）——
# 准备（连接/检查）0~5，拉取 5~85，启动 85~100
PHASE_PREPARE_END = 5.0
PHASE_PULL_BASE = 5.0
PHASE_PULL_SPAN = 80.0  # → 85
PHASE_UP_BASE = 85.0
PHASE_UP_SPAN = 15.0  # → 100

# docker pull: Downloading [====>] 12.34MB/56.78MB
_SIZE_RE = re.compile(
    r"(?P<done>\d+(?:\.\d+)?)\s*(?P<du>kB|MB|GB|B)\s*/\s*"
    r"(?P<total>\d+(?:\.\d+)?)\s*(?P<tu>kB|MB|GB|B)",
    re.IGNORECASE,
)
_PCT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:\.\d+)?)\s*%")
# 层 ID（短/长 hash）或镜像名：状态
_LAYER_RE = re.compile(
    r"^(?P<id>[0-9a-f]{12,64}|[a-z0-9][\w./:-]*?):\s*(?P<rest>.+)$",
    re.IGNORECASE,
)
_BUILDKIT_RE = re.compile(r"^#(?P<n>\d+)\s+(?P<rest>.+)$")

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
    """
    综合阶段进度 + 从 docker 输出解析的拉取进度。

    规则：
    - 全局单调：百分比只增不减
    - pull 阶段在命令结束前最高到阶段末尾的 96%，由 complete_phase 收满
    - 未见层取加权平均；未知总层数时用「已见层」并封顶，避免过早到 100%
    - 解析不到数值时按输出行数缓慢爬升，避免长时间卡死
    """

    phase: str = "idle"
    phase_base: float = 0.0
    phase_span: float = 100.0
    layer_ratio: dict[str, float] = field(default_factory=dict)
    layer_weight: dict[str, float] = field(default_factory=dict)
    last_percent: float = 0.0
    activity_lines: int = 0

    def set_phase(self, name: str, base: float, span: float) -> float:
        self.phase = name
        self.phase_base = float(base)
        self.phase_span = float(span)
        self.activity_lines = 0
        if name == "pull":
            self.layer_ratio.clear()
            self.layer_weight.clear()
        # 进入新阶段时至少落到阶段起点，且不回退
        return self._commit(self.phase_base)

    def complete_phase(self) -> float:
        return self._commit(self.phase_base + self.phase_span)

    def feed_line(self, line: str) -> float | None:
        """解析一行输出；有进度更新时返回新百分比，否则 None。"""
        text = (line or "").strip()
        if not text:
            return None

        self.activity_lines += 1

        if self.phase == "pull":
            local = self._pull_local(text)
            # 命令未结束前封顶，留给 complete_phase
            local = min(local, 0.96)
            return self._commit(self.phase_base + self.phase_span * local)

        if self.phase == "up":
            local = self._up_local(text)
            local = min(local, 0.90)
            return self._commit(self.phase_base + self.phase_span * local)

        return None

    def _pull_local(self, text: str) -> float:
        layer_id, rest = self._split_layer(text)
        ratio, total_bytes = self._parse_ratio(rest)
        lower = rest.lower()

        if ratio is None and layer_id:
            if any(h in lower for h in ("pull complete", "already exists", "download complete")):
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

        # 镜像级提示：登记伪层，保证「开始拉取」有反馈
        if "pulling from" in lower or "pulling fs layer" in lower:
            key = layer_id or f"img:{self.activity_lines}"
            self.layer_ratio.setdefault(key, 0.02)

        if any(h in lower for h in ("downloaded newer image", "image is up to date")):
            # 整镜像完成：轻微推高，仍由封顶限制
            if self.layer_ratio:
                for k, v in list(self.layer_ratio.items()):
                    if v < 1.0:
                        self.layer_ratio[k] = max(v, 0.99)
            else:
                self.layer_ratio["image-done"] = 1.0

        if self.layer_ratio:
            return self._weighted_avg()

        # 无层信息：按活跃行缓慢爬升到 40% 局部
        return min(0.04 + self.activity_lines * 0.004, 0.40)

    def _up_local(self, text: str) -> float:
        lower = text.lower()
        # compose up 几乎没有可靠百分比；用事件 + 行数爬升
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
            # 未知大小的层给基础权重，避免被大层完全淹没也不至于均等失真
            if w <= 1.0:
                w = 1.0
            total_w += w
            acc += max(0.0, min(1.0, ratio)) * w
        if total_w <= 0:
            return 0.0
        avg = acc / total_w
        n = max(len(self.layer_ratio), 1)
        # 预留尚未出现的层，避免前几层完成就冲到接近阶段末尾
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

    def format_log(self, percent: float, detail: str = "") -> str:
        bar = render_bar(percent)
        labels = {
            "idle": "待命",
            "prepare": "准备",
            "pull": "拉取镜像",
            "up": "启动容器",
            "deploy": "部署",
        }
        phase = labels.get(self.phase or "deploy", self.phase or "部署")
        extra = f" | {detail}" if detail else ""
        return f"进度 {bar} ({phase}){extra}"
