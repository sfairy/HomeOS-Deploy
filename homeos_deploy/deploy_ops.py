"""远程 docker / compose 操作。"""

from __future__ import annotations

import shlex
from typing import Callable, Optional

from homeos_deploy.defaults import GHCR_REGISTRY
from homeos_deploy.progress import DeployProgress
from homeos_deploy.ssh_session import SSHSession

OutputCallback = Callable[[str], None]
ProgressCallback = Callable[[float, str], None]


def _sudo_wrap(sudo_password: str, inner_command: str) -> str:
    """
    用 sudo -S 执行 inner_command。
    sudo 密码从管道传入；inner 在 bash -lc 中运行，避免与业务命令抢 stdin。
    """
    pwd = shlex.quote(sudo_password)
    wrapped = shlex.quote(inner_command)
    return f"printf '%s\\n' {pwd} | sudo -S -p '' bash -lc {wrapped}"


def _in_workdir(workdir: str, inner: str) -> str:
    wd = shlex.quote(workdir)
    return f"cd {wd} && {inner}"


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
        user_q = shlex.quote(ghcr_user)
        token_q = shlex.quote(ghcr_token)
        inner = (
            f"printf %s {token_q} | docker login {GHCR_REGISTRY} "
            f"-u {user_q} --password-stdin"
        )
        cmd = _sudo_wrap(sudo_password, inner)
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_pull(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        # --progress=plain 保证可解析文本；仍可能带层进度百分比
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, "docker compose pull --progress=plain"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=True)
        return code

    def compose_up(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, "docker compose up -d --progress=plain"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=True)
        return code

    def compose_ps(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, "docker compose ps"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_logs(
        self,
        workdir: str,
        sudo_password: str,
        service: str = "",
        tail: int = 200,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        svc = f" {shlex.quote(service)}" if service.strip() else ""
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, f"docker compose logs --tail={int(tail)}{svc}"),
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
        svc = f" {shlex.quote(service)}" if service.strip() else ""
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, f"docker compose restart{svc}"),
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
        svc = f" {shlex.quote(service)}" if service.strip() else ""
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, f"docker compose stop{svc}"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_down(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> int:
        # 不加 -v，避免误删数据卷
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, "docker compose down"),
        )
        code, _ = self.session.run(cmd, on_output=on_output, get_pty=False)
        return code

    def compose_services(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> list[str]:
        cmd = _sudo_wrap(
            sudo_password,
            _in_workdir(workdir, "docker compose config --services"),
        )
        code, out = self.session.run(cmd, on_output=on_output, get_pty=False)
        if code != 0:
            raise RuntimeError(f"获取服务列表失败，退出码 {code}")
        services: list[str] = []
        for line in out.splitlines():
            name = line.strip()
            if not name:
                continue
            # 过滤 sudo / 噪声行，保留 compose 服务名
            if " " in name or ":" in name or name.startswith("["):
                continue
            if name.lower().startswith("sudo") or name.lower().startswith("password"):
                continue
            services.append(name)
        return services

    def check_deploy_ready(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
    ) -> None:
        """部署前检查：目录存在且含 compose 文件（经 sudo，与后续 compose 权限一致）。"""
        wd = shlex.quote(workdir)
        inner = (
            f"if [ ! -d {wd} ]; then echo 'WORKDIR_MISSING'; exit 2; fi; "
            f"if [ -f {wd}/compose.yaml ] || [ -f {wd}/compose.yml ] "
            f"|| [ -f {wd}/docker-compose.yml ] || [ -f {wd}/docker-compose.yaml ]; "
            f"then echo 'COMPOSE_OK'; exit 0; "
            f"else echo 'COMPOSE_MISSING'; exit 3; fi"
        )
        cmd = _sudo_wrap(sudo_password, inner)
        code, out = self.session.run(cmd, on_output=on_output, get_pty=False)
        text = (out or "").strip()
        if code == 2 or "WORKDIR_MISSING" in text:
            raise ValueError(f"远程工作目录不存在：{workdir}")
        if code == 3 or "COMPOSE_MISSING" in text:
            raise ValueError(
                f"工作目录中未找到 compose 文件（compose.yaml / docker-compose.yml）：{workdir}"
            )
        if code != 0:
            raise RuntimeError(f"部署前置检查失败，退出码 {code}")

    def deploy(
        self,
        workdir: str,
        sudo_password: str,
        on_output: Optional[OutputCallback] = None,
        on_progress: Optional[ProgressCallback] = None,
    ) -> int:
        progress = DeployProgress()

        def _report(pct: float, detail: str = "") -> None:
            if on_progress is not None:
                on_progress(pct, detail)
            if on_output is not None and detail:
                on_output(progress.format_log(pct, detail))

        def _on_line(phase_detail: str) -> OutputCallback:
            last_logged = [-1.0]

            def handler(line: str) -> None:
                if on_output is not None:
                    on_output(line)
                pct = progress.feed_line(line)
                if pct is None:
                    return
                if on_progress is not None:
                    on_progress(pct, phase_detail)
                # 日志里每变化 >=1% 写一条进度条，避免刷屏
                if abs(pct - last_logged[0]) >= 1.0 or pct >= 99.5:
                    last_logged[0] = pct
                    if on_output is not None:
                        on_output(progress.format_log(pct, phase_detail))

            return handler

        pct = progress.set_phase("pull", 0.0, 80.0)
        _report(pct, "开始拉取镜像")
        code = self.compose_pull(
            workdir, sudo_password, on_output=_on_line("compose pull")
        )
        if code != 0:
            _report(progress.last_percent, "拉取失败")
            return code
        pct = progress.complete_phase()
        _report(pct, "镜像拉取完成")

        pct = progress.set_phase("up", 80.0, 20.0)
        _report(pct, "开始启动容器")
        code = self.compose_up(
            workdir, sudo_password, on_output=_on_line("compose up")
        )
        if code != 0:
            _report(progress.last_percent, "启动失败")
            return code
        progress.last_percent = 100.0
        _report(100.0, "部署完成")
        return code
