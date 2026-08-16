"""远程 docker / compose 操作。"""

from __future__ import annotations

from typing import Callable, Optional

from homeos_deploy.compose_view import format_compose_ps
from homeos_deploy.defaults import GHCR_REGISTRY
from homeos_deploy.log_filter import should_show_log_line
from homeos_deploy.progress import (
    PHASE_PULL_BASE,
    PHASE_PULL_SPAN,
    PHASE_UP_BASE,
    PHASE_UP_SPAN,
    DeployProgress,
)
from homeos_deploy.ssh_session import SSHSession

OutputCallback = Callable[[str], None]
# overall%, detail, pull_percent(0~100|None)
ProgressCallback = Callable[[float, str, float | None], None]


def posix_quote(value: str) -> str:
    """始终按 POSIX / bash 规则加引号（避免 Windows 上 shlex.quote 用双引号）。"""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def normalize_workdir(raw: str) -> str:
    """规范化远端工作目录：去空白、统一斜杠、去掉末尾 /。"""
    path = (raw or "").strip().replace("\\", "/")
    while "//" in path:
        path = path.replace("//", "/")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def validate_workdir(raw: str) -> str:
    """校验并返回规范化后的工作目录；非法则抛 ValueError。"""
    path = normalize_workdir(raw)
    if not path:
        raise ValueError("请填写远程工作目录。")
    if not (path.startswith("/") or path.startswith("~/") or path == "~"):
        raise ValueError(
            "远程工作目录须为绝对路径（以 / 开头），"
            "例如 /vol1/1000/docker/homeos"
        )
    if any(ch in path for ch in ("\n", "\r", "\0", ";", "|", "&", "`")):
        raise ValueError("远程工作目录包含非法字符。")
    return path


def _workdir_assign(workdir: str) -> str:
    """在远端 bash 中把工作目录赋给 WD（支持 ~/ 展开为 $HOME）。"""
    path = normalize_workdir(workdir)
    if path == "~":
        return 'WD="$HOME"'
    if path.startswith("~/"):
        rest = path[2:].replace('"', '\\"')
        return f'WD="$HOME/{rest}"'
    return f"WD={posix_quote(path)}"


def _wrap_sudo(sudo_password: str, inner_command: str) -> str:
    """
    用 sudo -S 执行 inner_command。
    使用 bash -c（非 login shell），避免 -l 改变初始目录干扰 cd。
    """
    pwd = posix_quote(sudo_password)
    wrapped = posix_quote(inner_command)
    return f"printf '%s\\n' {pwd} | sudo -S -p '' bash -c {wrapped}"


def _looks_like_workdir(line: str) -> bool:
    """机器输出里挑出真正的工作目录路径（排除 sudo / chdir 噪音）。"""
    text = (line or "").strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    return text.startswith("/") or text.startswith("~/") or text == "~"


_DUMP_UP_FAILURE_SH = r"""
echo "=== 容器状态 ==="
docker compose --project-directory "$WD" ps -a
echo "=== 异常容器 ==="
failed_ids=""
for id in $(docker compose --project-directory "$WD" ps -aq 2>/dev/null); do
  [ -z "$id" ] && continue
  name=$(docker inspect -f '{{.Name}}' "$id" 2>/dev/null | sed "s|^/||")
  st=$(docker inspect -f '{{.State.Status}}' "$id")
  code=$(docker inspect -f '{{.State.ExitCode}}' "$id")
  health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$id")
  echo "NAME=$name STATUS=$st EXIT=$code HEALTH=$health"
  interesting=0
  [ "$health" = "unhealthy" ] && interesting=1
  [ "$st" = "restarting" ] && interesting=1
  [ "$st" = "dead" ] && interesting=1
  [ "$st" = "exited" ] && [ "$code" != "0" ] && interesting=1
  if [ "$interesting" = "1" ]; then
    failed_ids="$failed_ids $id"
  fi
done
if [ -z "$failed_ids" ]; then
  echo "=== 最近日志（未定位到异常容器） ==="
  docker compose --project-directory "$WD" logs --tail=40
else
  for id in $failed_ids; do
    svc=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")
    name=$(docker inspect -f '{{.Name}}' "$id" | sed "s|^/||")
    echo "=== 日志: ${svc:-$name} ==="
    docker logs --tail=80 "$id" 2>&1
  done
fi
"""


def _compose_script(
    workdir: str,
    compose_args: str,
    extra_env: str = "",
) -> str:
    """在 WD 下执行 docker compose（--project-directory，不依赖 cd）。"""
    assign = _workdir_assign(workdir)
    env = f"export {extra_env}; " if extra_env else ""
    return (
        f"{assign}; "
        f'if [ ! -d "$WD" ]; then echo "WORKDIR_MISSING:$WD" >&2; exit 2; fi; '
        f'{env}docker compose --project-directory "$WD" {compose_args}'
    )


class DeployOps:
    def __init__(self, session: SSHSession) -> None:
        self.session = session

    def docker_login(
        self,
        ghcr_user: str,
        ghcr_token: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        user_q = posix_quote(ghcr_user)
        token_q = posix_quote(ghcr_token)
        inner = (
            f"printf %s {token_q} | docker login {GHCR_REGISTRY} "
            f"-u {user_q} --password-stdin"
        )
        cmd = _wrap_sudo(sudo_password, inner)
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_pull(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        cmd = _wrap_sudo(
            sudo_password,
            _compose_script(
                workdir,
                "pull",
                extra_env="COMPOSE_PROGRESS=plain",
            ),
        )
        # COMPOSE_PROGRESS=plain：禁止 Compose v2 在 PTY 下用多行 TUI 刷屏。
        # get_pty=True：docker 层进度仍用 \r 刷新，进度条才能解析。
        # 旧 Compose 可能忽略该环境变量；控制台侧会再滤掉 TUI 帧。
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=True)
        return code

    def compose_up(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        cmd = _wrap_sudo(
            sudo_password,
            _compose_script(workdir, "up -d"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def dump_up_failure(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> None:
        """启动失败后只收集异常容器的状态与日志。"""
        assign = _workdir_assign(workdir)
        inner = f"{assign}; {_DUMP_UP_FAILURE_SH.strip()}"
        cmd = _wrap_sudo(sudo_password, inner)
        self.session.run(cmd, on_output=on_output, get_pty=False)

    def compose_ps(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        attempts = (
            "ps --format json",
            'ps --format "{{.Service}}\\t{{.Status}}\\t{{.Ports}}"',
            "ps",
        )
        last_code = 1
        last_out = ""
        for args in attempts:
            cmd = _wrap_sudo(
                sudo_password, _compose_script(workdir, args)
            )
            last_code, last_out = self.session.run(
                cmd, on_output=None, get_pty=False
            )
            if last_code != 0:
                continue
            lines = format_compose_ps(last_out)
            if lines:
                if on_output is not None:
                    for ln in lines:
                        on_output(ln)
                return 0
            if args == "ps":
                break
        if on_output is not None:
            for ln in (last_out or "").splitlines():
                if should_show_log_line(ln):
                    on_output(ln)
        return last_code

    def compose_logs(
        self,
        workdir: str,
        sudo_password: str,
        service: str = "",
        tail: int = 200,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        svc = f" {posix_quote(service)}" if service.strip() else ""
        cmd = _wrap_sudo(
            sudo_password,
            _compose_script(workdir, f"logs --tail={int(tail)}{svc}"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_restart(
        self,
        workdir: str,
        sudo_password: str,
        service: str = "",
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        svc = f" {posix_quote(service)}" if service.strip() else ""
        cmd = _wrap_sudo(
            sudo_password,
            _compose_script(workdir, f"restart{svc}"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_stop(
        self,
        workdir: str,
        sudo_password: str,
        service: str = "",
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        svc = f" {posix_quote(service)}" if service.strip() else ""
        cmd = _wrap_sudo(
            sudo_password,
            _compose_script(workdir, f"stop{svc}"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_down(
        self,
        workdir: str,
        sudo_password: str,
        remove_volumes: bool = False,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        args = "down -v" if remove_volumes else "down"
        cmd = _wrap_sudo(sudo_password, _compose_script(workdir, args))
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_services(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> list[str]:
        cmd = _wrap_sudo(
            sudo_password,
            _compose_script(workdir, "config --services"),
        )
        code, out = self.session.run(cmd, on_output=on_output, get_pty=False)
        if code != 0:
            raise RuntimeError(f"获取服务列表失败，退出码 {code}")
        services: list[str] = []
        for line in out.splitlines():
            name = line.strip()
            if not name:
                continue
            if " " in name or ":" in name or name.startswith("["):
                continue
            if name.lower().startswith("sudo") or name.lower().startswith("password"):
                continue
            if name.startswith("WORKDIR_MISSING"):
                continue
            services.append(name)
        return services

    def check_deploy_ready(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> str:
        """
        部署前检查：目录存在且含 compose 文件。
        返回远端解析后的工作目录路径（便于日志确认）。
        """
        workdir = validate_workdir(workdir)
        assign = _workdir_assign(workdir)
        inner = (
            f"{assign}; "
            f'if [ ! -d "$WD" ]; then echo WORKDIR_MISSING; echo "$WD"; exit 2; fi; '
            f'if [ -f "$WD/compose.yaml" ] || [ -f "$WD/compose.yml" ] '
            f'|| [ -f "$WD/docker-compose.yml" ] || [ -f "$WD/docker-compose.yaml" ]; '
            f'then echo COMPOSE_OK; echo "$WD"; exit 0; '
            f"else echo COMPOSE_MISSING; echo \"$WD\"; exit 3; fi"
        )
        cmd = _wrap_sudo(sudo_password, inner)
        # 机器标记不刷控制台；由调用方写友好日志
        code, out = self.session.run(cmd, on_output=None, get_pty=False)
        text = (out or "").strip()
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        resolved = ""
        for ln in reversed(lines):
            if not should_show_log_line(ln):
                continue
            if ln in ("COMPOSE_OK", "COMPOSE_MISSING", "WORKDIR_MISSING"):
                continue
            if ln.startswith("WORKDIR_MISSING"):
                continue
            if _looks_like_workdir(ln):
                resolved = ln
                break

        if code == 2 or "WORKDIR_MISSING" in text:
            shown = resolved or workdir
            raise ValueError(f"远程工作目录不存在：{shown}")
        if code == 3 or "COMPOSE_MISSING" in text:
            shown = resolved or workdir
            raise ValueError(
                "工作目录中未找到编排文件"
                f"（compose.yaml / docker-compose.yml）：{shown}"
            )
        if code != 0:
            # 仍把失败输出透出，便于排查（过滤噪音）
            if on_output is not None:
                for ln in lines:
                    if should_show_log_line(ln):
                        on_output(ln)
            raise RuntimeError(f"部署前置检查失败，退出码 {code}")
        return resolved or workdir

    def deploy(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> int:
        workdir = validate_workdir(workdir)
        progress = DeployProgress()

        def _emit(line: str) -> None:
            if on_output is not None and should_show_log_line(line):
                on_output(line)

        def _report(
            pct: float, detail: str = "", *, pull: float | None = None
        ) -> None:
            if on_progress is not None:
                on_progress(pct, detail, pull)
            if on_output is not None and detail:
                on_output(f"→ {detail}")

        def _on_line(phase_detail: str) -> OutputCallback:
            last_logged = [-1.0]
            last_ui = [-1.0]

            def handler(line: str) -> None:
                pct = progress.feed_line(line)
                _emit(line)
                if pct is None:
                    return
                pull_pct = (
                    progress.last_pull_percent if progress.phase == "pull" else None
                )
                if abs(pct - last_ui[0]) >= 0.5:
                    last_ui[0] = pct
                    if on_progress is not None:
                        on_progress(pct, phase_detail, pull_pct)
                # 拉取：控制台只留一条进度，原地刷新。启动阶段进度只走顶栏，避免和容器事件交织。
                if progress.phase != "pull" or on_output is None:
                    return
                metric = pull_pct if pull_pct is not None else pct
                if abs(metric - last_logged[0]) < 1.0 and pct < 99.0:
                    return
                last_logged[0] = metric
                on_output(progress.format_log(pct, phase_detail))

            return handler

        pct = progress.set_phase("pull", PHASE_PULL_BASE, PHASE_PULL_SPAN)
        _report(pct, "开始拉取镜像", pull=0.0)
        code = self.compose_pull(
            workdir, sudo_password, on_output=_on_line("拉取镜像")
        )
        if code != 0:
            _report(progress.last_percent, "拉取失败", pull=progress.last_pull_percent)
            return code
        pct = progress.complete_phase()
        _report(pct, "镜像拉取完成", pull=100.0)

        pct = progress.set_phase("up", PHASE_UP_BASE, PHASE_UP_SPAN)
        _report(pct, "开始启动容器", pull=100.0)
        code = self.compose_up(
            workdir, sudo_password, on_output=_on_line("启动容器")
        )
        if code != 0:
            _report(progress.last_percent, "启动失败", pull=100.0)
            if on_output is not None:
                on_output("—— 启动失败诊断 ——")
            try:
                self.dump_up_failure(
                    workdir,
                    sudo_password,
                    on_output=_emit,
                )
            except Exception as exc:
                _emit(f"收集诊断信息失败：{exc}")
            return code
        progress.complete_phase()
        _report(100.0, "部署完成", pull=100.0)
        return code
