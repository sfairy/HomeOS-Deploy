"""把 docker compose ps 收成适合控制台的短表。"""

from __future__ import annotations

import json
import re
import unicodedata

from homeos_deploy.log_filter import clean_log_text, should_show_log_line

_UP_RE = re.compile(
    r"Up(?:\s+About)?(?:\s+an?)?\s*(?:(?P<n>\d+)\s+)?(?P<u>second|minute|hour|day|week|month)s?",
    re.I,
)
_UNIT_ZH = {
    "second": "秒",
    "minute": "分钟",
    "hour": "小时",
    "day": "天",
    "week": "周",
    "month": "月",
}
_PUB_RE = re.compile(
    r"(?:0\.0\.0\.0|\[::\]|::):(?P<host>\d+)->(?P<target>\d+)",
    re.I,
)


def format_compose_ps(raw: str) -> list[str]:
    """把 compose ps 原始输出格式化成短表；无法识别则返回空列表。"""
    rows = _parse_json_rows(raw)
    if not rows:
        rows = _parse_tsv_rows(raw)
    if not rows:
        return []
    rendered = [_render_row(r) for r in rows]
    rendered = [r for r in rendered if r["service"]]
    if not rendered:
        return []
    w_svc = max(_disp_len("服务"), max(_disp_len(r["service"]) for r in rendered))
    w_st = max(_disp_len("状态"), max(_disp_len(r["status"]) for r in rendered))
    lines = [_pad("服务", w_svc) + "  " + _pad("状态", w_st) + "  端口"]
    for r in rendered:
        ports = r["ports"] or "—"
        lines.append(_pad(r["service"], w_svc) + "  " + _pad(r["status"], w_st) + "  " + ports)
    return lines


def _parse_json_rows(raw: str) -> list[dict]:
    text = clean_log_text(raw or "")
    blob = "\n".join(
        ln for ln in text.splitlines() if should_show_log_line(ln) or ln.strip().startswith(("{", "["))
    ).strip()
    if not blob:
        return []
    if blob.startswith("["):
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    rows: list[dict] = []
    for ln in blob.splitlines():
        ln = ln.strip()
        if not ln.startswith("{"):
            continue
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _parse_tsv_rows(raw: str) -> list[dict]:
    rows: list[dict] = []
    for ln in (raw or "").splitlines():
        text = clean_log_text(ln)
        if not text or not should_show_log_line(text):
            continue
        if "\t" not in text:
            continue
        parts = [p.strip() for p in text.split("\t")]
        if len(parts) < 2:
            continue
        if parts[0].lower() in ("service", "name", "names"):
            continue
        service, status = parts[0], parts[1]
        ports = parts[2] if len(parts) > 2 else ""
        rows.append({"Service": service, "Status": status, "Ports": ports})
    return rows


def _render_row(row: dict) -> dict[str, str]:
    service = str(row.get("Service") or row.get("Name") or "").strip()
    if service.startswith("/"):
        service = service[1:]
    status_raw = str(row.get("Status") or row.get("State") or "").strip()
    health = str(row.get("Health") or "").strip()
    return {
        "service": service,
        "status": _short_status(status_raw, health),
        "ports": _short_ports_row(row),
    }


def _short_status(status: str, health: str = "") -> str:
    s = (status or "").lower()
    h = (health or "").lower()
    if "unhealthy" in s or h == "unhealthy":
        label = "不健康"
    elif "restarting" in s:
        label = "重启中"
    elif "paused" in s:
        label = "已暂停"
    elif "dead" in s:
        label = "已停止"
    elif s.startswith("exited") or "exited" in s:
        label = "已退出" if "(0)" in status else "异常退出"
    elif "healthy" in s or h == "healthy":
        label = "健康"
    elif "starting" in s or h == "starting":
        label = "启动中"
    elif s.startswith("up") or "running" in s:
        label = "运行中"
    else:
        label = status or "未知"
    age = _uptime_zh(status)
    if age:
        return f"{label} · {age}"
    return label


def _uptime_zh(status: str) -> str:
    m = _UP_RE.search(status or "")
    if not m:
        return ""
    n = m.group("n")
    unit = _UNIT_ZH.get((m.group("u") or "").lower(), "")
    if not unit:
        return ""
    if n:
        return f"{n} {unit}"
    return f"1 {unit}"


def _short_ports_row(row: dict) -> str:
    pubs = row.get("Publishers") or row.get("publishers")
    if isinstance(pubs, list) and pubs:
        seen: list[str] = []
        for item in pubs:
            if not isinstance(item, dict):
                continue
            host = item.get("PublishedPort") or item.get("published_port")
            target = item.get("TargetPort") or item.get("Target") or item.get("target_port")
            url = str(item.get("URL") or item.get("url") or "")
            if not host:
                continue
            if url in ("::", "[::]"):
                continue
            text = str(int(host)) if str(host) == str(target) else f"{host}→{target}"
            if text not in seen:
                seen.append(text)
        return ", ".join(seen)
    return _short_ports(str(row.get("Ports") or ""))


def _short_ports(ports: str) -> str:
    if not ports or ports in ("-", "—"):
        return ""
    seen: list[str] = []
    for m in _PUB_RE.finditer(ports):
        host, target = m.group("host"), m.group("target")
        text = host if host == target else f"{host}→{target}"
        if text not in seen:
            seen.append(text)
    return ", ".join(seen)


def _disp_len(text: str) -> int:
    n = 0
    for ch in text:
        n += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return n


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _disp_len(text))
