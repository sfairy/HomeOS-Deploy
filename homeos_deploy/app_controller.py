"""业务编排：连接 / 登录 / 部署 / 运维、里程碑与步骤门禁（无 UI 控件）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from homeos_deploy.config_store import AppConfig, resolve_sudo_password, save_config
from homeos_deploy.deploy_ops import DeployOps, validate_workdir
from homeos_deploy.ssh_session import SSHSession

STEP_COUNT = 4


@dataclass
class Milestones:
    connected: bool = False
    logged_in: bool = False
    deployed: bool = False


@dataclass
class GateResult:
    ok: bool
    error: str = ""
    confirm: str = ""  # 非空时需 UI 确认后继续
    need_connect: bool = False  # 进入 Deploy/Ops 前需先确保已连接


@dataclass
class ControllerHooks:
    """UI 注入的回调（均应可在任意线程调用；UI 侧自行 after 回主线程）。"""

    log: Callable[[str], None]
    progress: Callable[..., None]  # (overall%, detail, pull%=None)
    set_status: Callable[[bool, str], None]
    on_milestones: Callable[[Milestones], None]
    schedule: Callable[[Callable[[], None]], None]  # 主线程调度，如 root.after(0, fn)


class AppController:
    def __init__(
        self,
        session: SSHSession,
        ops: DeployOps,
        hooks: ControllerHooks,
    ) -> None:
        self.session = session
        self.ops = ops
        self.hooks = hooks
        self.milestones = Milestones()
        self._conn_key: Optional[tuple[str, int, str, str]] = None
        self.busy = False

    # —— helpers —— #

    def sudo(self, cfg: AppConfig) -> str:
        return resolve_sudo_password(cfg)

    def ssh_missing_fields(self, cfg: AppConfig) -> list[str]:
        missing: list[str] = []
        if not cfg.host:
            missing.append("主机")
        if cfg.port <= 0:
            missing.append("端口")
        if not cfg.user:
            missing.append("用户名")
        if not cfg.ssh_password:
            missing.append("密码")
        return missing

    def milestone_for_step(self, idx: int) -> bool:
        if idx == 0:
            return self.milestones.connected
        if idx == 1:
            return self.milestones.logged_in
        if idx == 2:
            return self.milestones.deployed
        return self.milestones.deployed or self.milestones.connected

    def _emit_milestones(self) -> None:
        self.hooks.on_milestones(self.milestones)

    def _conn_identity(self, cfg: AppConfig) -> tuple[str, int, str, str]:
        return (cfg.host, cfg.port, cfg.user, cfg.ssh_password)

    def ensure_connected(self, cfg: AppConfig) -> None:
        missing = self.ssh_missing_fields(cfg)
        if missing:
            raise ValueError(
                "请先填写：" + "、".join(missing) + "；或通过「导入配置」载入。"
            )

        key = self._conn_identity(cfg)
        if self.session.connected and self._conn_key == key:
            return

        if self.session.connected:
            self.hooks.log("连接参数已变更，正在重新连接…")
            self.session.close()
            self._conn_key = None

        self.hooks.log(f"正在连接 {cfg.user}@{cfg.host}:{cfg.port} …")
        self.session.connect(
            cfg.host,
            cfg.port,
            cfg.user,
            cfg.ssh_password,
        )
        self._conn_key = key
        self.milestones.connected = True
        self.hooks.schedule(
            lambda: self.hooks.set_status(
                True, f"已连接 {cfg.user}@{cfg.host}:{cfg.port}"
            )
        )
        self.hooks.log("远程连接成功。")
        self.hooks.schedule(self._emit_milestones)

    def disconnect(self) -> None:
        self.session.close()
        self._conn_key = None
        self.milestones.connected = False
        self.hooks.set_status(False, "未连接")
        self.hooks.log("已断开远程连接。")
        self._emit_milestones()

    def cancel(self) -> None:
        self.session.cancel()
        self.hooks.log("已请求取消…")

    def mark_disconnected(self) -> None:
        self.milestones.connected = False
        self._emit_milestones()

    def reset_connection_state(self) -> None:
        if self.session.connected:
            self.session.close()
        self._conn_key = None
        self.milestones.connected = False
        self.hooks.set_status(False, "未连接")
        self._emit_milestones()

    # —— gates —— #

    def validate_leaving_step(
        self, from_idx: int, to_idx: int, cfg: AppConfig
    ) -> GateResult:
        """前进校验；回退一律放行。"""
        if to_idx <= from_idx:
            return GateResult(ok=True)

        confirm = ""
        for step in range(from_idx, to_idx):
            if step == 0:
                missing = self.ssh_missing_fields(cfg)
                if not cfg.workdir:
                    missing.append("工作目录")
                if missing:
                    return GateResult(
                        ok=False,
                        error="请先填写：" + "、".join(missing) + "，再进入下一步。",
                    )
                try:
                    if cfg.workdir:
                        validate_workdir(cfg.workdir)
                except ValueError as exc:
                    return GateResult(ok=False, error=str(exc))
            if step == 1:
                if not cfg.ghcr_user or not cfg.ghcr_token:
                    confirm = (
                        "尚未填写镜像仓库用户名或访问令牌。\n"
                        "私有镜像可能无法拉取，仍要继续？"
                    )

        need_connect = to_idx >= 2 and not self.session.connected
        return GateResult(ok=True, confirm=confirm, need_connect=need_connect)

    # —— operations (worker-thread safe; cfg must be snapshot) —— #

    def test_connect(self, cfg: AppConfig) -> None:
        missing = self.ssh_missing_fields(cfg)
        if missing:
            raise ValueError("请先填写：" + "、".join(missing) + "。")

        self.session.close()
        self._conn_key = None
        self.hooks.schedule(lambda: self.hooks.set_status(False, "连接中…"))
        self.ensure_connected(cfg)

        def _on_test_output(line: str) -> None:
            if line.startswith("Could not chdir to home directory"):
                return
            if line.strip() == "/":
                return
            self.hooks.log(line)

        code, _out = self.session.run("pwd; uname -a", on_output=_on_test_output)
        if code != 0:
            raise RuntimeError(f"测试命令失败，退出码 {code}")
        save_config(cfg)
        self.milestones.connected = True
        self.hooks.log("测试连接通过；配置已自动保存。")
        self.hooks.schedule(self._emit_milestones)

    def docker_login(self, cfg: AppConfig) -> None:
        if not cfg.ghcr_user or not cfg.ghcr_token:
            raise ValueError("请填写镜像仓库用户名与访问令牌。")
        self.ensure_connected(cfg)
        code = self.ops.docker_login(
            cfg.ghcr_user,
            cfg.ghcr_token,
            self.sudo(cfg),
            on_output=self.hooks.log,
        )
        if code != 0:
            raise RuntimeError(f"镜像仓库登录失败，退出码 {code}")
        self.hooks.log("镜像仓库登录成功。")
        save_config(cfg)
        self.milestones.logged_in = True
        self.hooks.schedule(self._emit_milestones)

    def deploy(self, cfg: AppConfig) -> None:
        cfg.workdir = validate_workdir(cfg.workdir)
        save_config(cfg)
        if not self.sudo(cfg):
            raise ValueError("远程命令需管理员权限，但密码为空。请填写登录密码。")

        self.hooks.progress(0.0, "准备部署…", 0.0)
        self.ensure_connected(cfg)
        self.hooks.progress(2.0, "检查工作目录…", 0.0)
        self.hooks.log(f"检查远程工作目录：{cfg.workdir}")
        resolved = self.ops.check_deploy_ready(
            cfg.workdir,
            self.sudo(cfg),
            on_output=self.hooks.log,
        )
        self.hooks.log(f"前置检查通过：{resolved}")
        self.hooks.progress(5.0, "前置检查通过，开始部署…", 0.0)

        if cfg.down_before_deploy:
            remove_vol = bool(cfg.down_remove_volumes)
            self.hooks.progress(6.0, "下线旧容器…", 0.0)
            if remove_vol:
                self.hooks.log("→ 部署前下线旧容器，并删除数据卷")
            else:
                self.hooks.log("→ 部署前下线旧容器（保留数据卷）")
            down_code = self.ops.compose_down(
                cfg.workdir,
                self.sudo(cfg),
                remove_volumes=remove_vol,
                on_output=self.hooks.log,
            )
            if down_code != 0:
                raise RuntimeError(f"部署前下线失败，退出码 {down_code}")
            self.hooks.log("旧容器已下线。")
            self.hooks.progress(8.0, "旧容器已下线，开始拉取…", 0.0)

        code = self.ops.deploy(
            cfg.workdir,
            self.sudo(cfg),
            on_output=self.hooks.log,
            on_progress=self.hooks.progress,
        )
        if code != 0:
            raise RuntimeError(f"部署失败，退出码 {code}")

        self.hooks.progress(100.0, "部署完成", 100.0)
        # 部署成功后自动查看一次状态，便于确认
        self.hooks.log("正在查看容器状态…")
        ps_code = self.ops.compose_ps(
            cfg.workdir,
            self.sudo(cfg),
            on_output=self.hooks.log,
        )
        if ps_code != 0:
            self.hooks.log(f"查看状态未成功（退出码 {ps_code}），部署本身已完成。")
        else:
            self.hooks.log("一键部署完成。")

        self.milestones.deployed = True
        self.hooks.schedule(self._emit_milestones)

    def compose_ps(self, cfg: AppConfig) -> None:
        cfg.workdir = validate_workdir(cfg.workdir)
        save_config(cfg)
        self.ensure_connected(cfg)
        code = self.ops.compose_ps(
            cfg.workdir,
            self.sudo(cfg),
            on_output=self.hooks.log,
        )
        if code != 0:
            raise RuntimeError(f"查看状态失败，退出码 {code}")

    def compose_logs(self, cfg: AppConfig, service: str, tail: int) -> None:
        cfg.workdir = validate_workdir(cfg.workdir)
        cfg.last_service = service
        save_config(cfg)
        self.ensure_connected(cfg)
        code = self.ops.compose_logs(
            cfg.workdir,
            self.sudo(cfg),
            service=service,
            tail=tail,
            on_output=self.hooks.log,
        )
        if code != 0:
            raise RuntimeError(f"查看日志失败，退出码 {code}")

    def compose_restart(self, cfg: AppConfig, service: str) -> None:
        cfg.workdir = validate_workdir(cfg.workdir)
        cfg.last_service = service
        save_config(cfg)
        self.ensure_connected(cfg)
        code = self.ops.compose_restart(
            cfg.workdir,
            self.sudo(cfg),
            service=service,
            on_output=self.hooks.log,
        )
        if code != 0:
            raise RuntimeError(f"重启失败，退出码 {code}")
        self.hooks.log("重启完成。")

    def compose_stop(self, cfg: AppConfig, service: str) -> None:
        cfg.workdir = validate_workdir(cfg.workdir)
        cfg.last_service = service
        save_config(cfg)
        self.ensure_connected(cfg)
        code = self.ops.compose_stop(
            cfg.workdir,
            self.sudo(cfg),
            service=service,
            on_output=self.hooks.log,
        )
        if code != 0:
            raise RuntimeError(f"停止失败，退出码 {code}")
        self.hooks.log("停止完成。")

    def compose_down(self, cfg: AppConfig) -> None:
        cfg.workdir = validate_workdir(cfg.workdir)
        save_config(cfg)
        self.ensure_connected(cfg)
        # 运维「下线」默认保留数据卷；删卷仅通过部署页开关在「部署前下线」时生效
        code = self.ops.compose_down(
            cfg.workdir,
            self.sudo(cfg),
            remove_volumes=False,
            on_output=self.hooks.log,
        )
        if code != 0:
            raise RuntimeError(f"下线失败，退出码 {code}")
        self.hooks.log("下线完成。")

    def refresh_services(self, cfg: AppConfig) -> list[str]:
        cfg.workdir = validate_workdir(cfg.workdir)
        self.ensure_connected(cfg)
        services = self.ops.compose_services(
            cfg.workdir,
            self.sudo(cfg),
            on_output=self.hooks.log,
        )
        self.hooks.log(f"已加载 {len(services)} 个服务。")
        return services
