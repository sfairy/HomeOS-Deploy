"""HomeOS Deploy 主窗口 —— Aether Dock 全屏科技风布局。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

from homeos_deploy import __version__
from homeos_deploy import theme as T
from homeos_deploy.app_controller import AppController, ControllerHooks, Milestones
from homeos_deploy.config_store import (
    AppConfig,
    clear_secrets,
    config_path,
    export_config,
    import_config,
    load_config,
    save_config,
)
from homeos_deploy.defaults import APP_NAME
from homeos_deploy.deploy_ops import DeployOps, normalize_workdir, validate_workdir
from homeos_deploy.ssh_session import SSHSession
from homeos_deploy.ui.action_bar import ActionBar
from homeos_deploy.ui.components import WidgetFactory, mono_font, ui_font
from homeos_deploy.ui.console import DeployConsole
from homeos_deploy.ui.constants import (
    SERVICE_ALL,
    STEP_TITLES,
    STEPS,
)
from homeos_deploy.ui.sidebar import SlimSidebar
from homeos_deploy.ui.steps import (
    StepWidgets,
    build_all_steps,
    set_progress,
    update_deploy_checklist,
)

ctk.set_appearance_mode("Dark")


class HomeOSDeployApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{__version__}")
        self.geometry("1100x720")
        self.minsize(980, 640)
        self.configure(fg_color=T.BG)

        self.cfg = load_config()
        self.session = SSHSession()
        self.ops = DeployOps(self.session)
        self._step = 0
        self._service_names: list[str] = []
        self._factory = WidgetFactory()

        hooks = ControllerHooks(
            log=self._ui_log,
            progress=self._ui_progress,
            set_status=self._set_status,
            on_milestones=self._on_milestones,
            schedule=lambda fn: self.after(0, fn),
        )
        self.controller = AppController(self.session, self.ops, hooks)

        self._build_layout()
        self._load_fields_from_config()
        self._show_step(0)
        self._set_status(False, "未连接")
        if self.cfg.is_empty():
            self.console.append(
                "系统就绪：参数为空。请填写表单，或使用左侧「导入配置」载入。"
            )
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # —— layout —— #

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = SlimSidebar(
            self,
            on_step=self._try_show_step,
            on_disconnect=self._disconnect,
            on_import=self._import_config,
            on_export=self._export_config,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.chrome = self.sidebar

        self.main = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        # 表单区贴合内容高度，剩余空间给控制台
        self.main.grid_rowconfigure(1, weight=0)
        self.main.grid_rowconfigure(2, weight=1, minsize=T.CONSOLE_MIN_H)
        self._body_wrap = self.main

        top = ctk.CTkFrame(self.main, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=T.PAD, pady=(10, 0))
        self.stage_label = ctk.CTkLabel(
            top,
            text="步骤 01",
            anchor="w",
            text_color=T.ACCENT,
            font=ui_font(11),
        )
        self.stage_label.pack(anchor="w")
        self.step_title = ctk.CTkLabel(
            top, text="", anchor="w", text_color=T.TEXT, font=ui_font(18, "bold")
        )
        self.step_title.pack(anchor="w")
        self.step_subtitle = ctk.CTkLabel(
            top, text="", anchor="w", text_color=T.MUTED, font=ui_font(11)
        )
        self.step_subtitle.pack(anchor="w")

        self.content = ctk.CTkFrame(
            self.main,
            fg_color=T.SURFACE,
            corner_radius=T.RADIUS,
            border_width=1,
            border_color=T.SURFACE_BORDER,
        )
        self.content.grid(row=1, column=0, sticky="ew", padx=T.PAD, pady=(6, 8))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=0)

        self.step_host = ctk.CTkFrame(
            self.content,
            fg_color="transparent",
            corner_radius=0,
            border_width=0,
        )
        self.step_host.grid(row=0, column=0, sticky="ew", padx=2, pady=(2, 0))
        self.step_host.grid_columnconfigure(0, weight=1)
        self.step_host.grid_rowconfigure(0, weight=0)

        self.steps: StepWidgets = build_all_steps(
            self.step_host,
            self._factory,
            on_clear_secrets=self._clear_secrets,
            on_save=lambda: self._save_all(),
            on_ps=self._do_ps,
            on_logs=self._do_logs,
            on_restart=self._do_restart,
            on_stop=self._do_stop,
            on_down=self._do_down,
            on_refresh_services=self._refresh_services,
        )

        self.action_bar = ActionBar(
            self.content,
            on_prev=self._prev_step,
            on_next=self._next_step,
            on_primary=self._primary_action,
            on_cancel=self._cancel_op,
            embedded=True,
        )
        self.action_bar.grid(row=1, column=0, sticky="ew")

        self.console = DeployConsole(self.main)
        self.console.grid(row=2, column=0, sticky="nsew", padx=T.PAD, pady=(0, T.PAD))

    # —— navigation —— #

    def _show_step(self, idx: int) -> None:
        self._step = idx
        title, subtitle = STEP_TITLES[idx]
        self.stage_label.configure(text=f"步骤  {idx + 1:02d}  /  {STEPS[idx][0]}")
        self.step_title.configure(text=title)
        self.step_subtitle.configure(text=subtitle)

        for i, frame in self.steps.frames.items():
            if i == idx:
                frame.grid(row=0, column=0, sticky="ew")
            else:
                frame.grid_forget()

        self.action_bar.set_step(idx)
        self.sidebar.set_current_step(idx)

        # 运维步：控制台略高一点（仍由控制台吃掉剩余高度）
        console_min = T.CONSOLE_OPS_MIN_H if idx == 3 else T.CONSOLE_MIN_H
        self.main.grid_rowconfigure(2, weight=1, minsize=console_min)

        if idx == 2:
            self._update_deploy_checklist()

    def _try_show_step(self, idx: int) -> None:
        if self.controller.busy:
            messagebox.showwarning(APP_NAME, "已有操作在进行中，请先等待或取消。")
            return
        if idx == self._step:
            return

        cfg = self._snapshot_cfg_or_warn()
        if cfg is None and idx > self._step:
            return
        if cfg is None:
            cfg = self.cfg

        gate = self.controller.validate_leaving_step(self._step, idx, cfg)
        if not gate.ok:
            messagebox.showwarning(APP_NAME, gate.error)
            return
        if gate.confirm:
            if not messagebox.askyesno(APP_NAME, gate.confirm):
                return

        if gate.need_connect:
            self._run_async(
                "准备连接",
                lambda: self.controller.ensure_connected(cfg),
                on_success=lambda: self._show_step(idx),
            )
            return

        self._show_step(idx)

    def _prev_step(self) -> None:
        if self.controller.busy:
            return
        if self._step > 0:
            self._show_step(self._step - 1)

    def _next_step(self) -> None:
        if self.controller.busy:
            return
        if self._step < len(STEPS) - 1:
            self._try_show_step(self._step + 1)

    def _primary_action(self) -> None:
        handlers = (
            self._test_connect,
            self._do_login,
            self._do_deploy,
            self._do_ps,
        )
        handlers[self._step]()

    # —— config / fields —— #

    def _set_entry(self, entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _selected_service(self) -> str:
        assert self.steps.service_manual and self.steps.service_menu
        manual = self.steps.service_manual.get().strip()
        if manual:
            return manual
        value = self.steps.service_menu.get().strip()
        if not value or value == SERVICE_ALL:
            return ""
        return value

    def _selected_tail(self) -> int:
        assert self.steps.tail_menu
        try:
            return int(self.steps.tail_menu.get())
        except ValueError:
            return 200

    def _sync_service_menu_from_config(self) -> None:
        assert self.steps.service_menu and self.steps.service_manual
        last = self.cfg.last_service.strip()
        values = [SERVICE_ALL] + list(self._service_names)
        if last and last not in self._service_names and last not in values:
            values.append(last)
        self.steps.service_menu.configure(values=values)
        if last and last in self._service_names:
            self.steps.service_menu.set(last)
            self._set_entry(self.steps.service_manual, "")
        elif last and last not in self._service_names:
            self.steps.service_menu.set(SERVICE_ALL)
            self._set_entry(self.steps.service_manual, last)
        else:
            self.steps.service_menu.set(SERVICE_ALL)
            self._set_entry(self.steps.service_manual, "")

    def _load_fields_from_config(self) -> None:
        e = self.steps.ssh_entries
        self._set_entry(e["host"], self.cfg.host)
        self._set_entry(e["port"], "" if self.cfg.port <= 0 else str(self.cfg.port))
        self._set_entry(e["user"], self.cfg.user)
        self._set_entry(e["ssh_password"], self.cfg.ssh_password)
        self._set_entry(e["workdir"], self.cfg.workdir)
        if self.steps.ghcr_user_entry and self.steps.ghcr_token_entry:
            self._set_entry(self.steps.ghcr_user_entry, self.cfg.ghcr_user)
            self._set_entry(self.steps.ghcr_token_entry, self.cfg.ghcr_token)
        if self.steps.deploy_down_before is not None:
            if self.cfg.down_before_deploy:
                self.steps.deploy_down_before.select()
            else:
                self.steps.deploy_down_before.deselect()
        if self.steps.deploy_down_volumes is not None:
            if self.cfg.down_before_deploy:
                self.steps.deploy_down_volumes.configure(state="normal")
                if self.cfg.down_remove_volumes:
                    self.steps.deploy_down_volumes.select()
                else:
                    self.steps.deploy_down_volumes.deselect()
            else:
                self.steps.deploy_down_volumes.deselect()
                self.steps.deploy_down_volumes.configure(state="disabled")
        self._sync_service_menu_from_config()
        if self.steps.config_path_label:
            self.steps.config_path_label.configure(text=f"本机配置 · {config_path()}")
        if self.steps.first_run_tip:
            if self.cfg.is_empty():
                self.steps.first_run_tip.grid(
                    row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8)
                )
            else:
                self.steps.first_run_tip.grid_forget()

    def _read_fields_into_config(self) -> AppConfig:
        e = self.steps.ssh_entries
        port_raw = e["port"].get().strip()
        if not port_raw:
            port = 0
        else:
            try:
                port = int(port_raw)
            except ValueError as exc:
                raise ValueError("端口必须是数字。") from exc
            if port <= 0 or port > 65535:
                raise ValueError("端口必须在 1–65535 之间。")
        self.cfg.host = e["host"].get().strip()
        self.cfg.port = port
        self.cfg.user = e["user"].get().strip()
        self.cfg.ssh_password = e["ssh_password"].get()
        wd_raw = e["workdir"].get()
        wd_norm = normalize_workdir(wd_raw)
        if wd_norm:
            self.cfg.workdir = validate_workdir(wd_norm)
            if e["workdir"].get() != self.cfg.workdir:
                self._set_entry(e["workdir"], self.cfg.workdir)
        else:
            self.cfg.workdir = ""
        if self.steps.ghcr_user_entry and self.steps.ghcr_token_entry:
            self.cfg.ghcr_user = self.steps.ghcr_user_entry.get().strip()
            self.cfg.ghcr_token = self.steps.ghcr_token_entry.get()
        if self.steps.deploy_down_before is not None:
            self.cfg.down_before_deploy = bool(self.steps.deploy_down_before.get())
        if (
            self.steps.deploy_down_volumes is not None
            and self.cfg.down_before_deploy
        ):
            self.cfg.down_remove_volumes = bool(self.steps.deploy_down_volumes.get())
        # 密钥 / sudo：界面不编辑；默认开启管理员权限，密码复用登录密码
        self.cfg.last_service = self._selected_service()
        return self.cfg

    def _snapshot_cfg_or_warn(self) -> Optional[AppConfig]:
        try:
            return self._read_fields_into_config()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return None

    def _require_workdir_cfg(self) -> Optional[AppConfig]:
        cfg = self._snapshot_cfg_or_warn()
        if cfg is None:
            return None
        try:
            cfg.workdir = validate_workdir(cfg.workdir)
            self._set_entry(self.steps.ssh_entries["workdir"], cfg.workdir)
            self._update_deploy_checklist()
        except ValueError as exc:
            self._show_step(0)
            messagebox.showerror(APP_NAME, str(exc))
            return None
        return cfg

    def _apply_config(self, cfg: AppConfig, note: str) -> None:
        if self.session.connected:
            self.controller.reset_connection_state()
            self.console.append("已导入新配置，已断开旧连接。")
        self.cfg = cfg
        self._service_names = []
        self._load_fields_from_config()
        self.console.append(note)

    def _save_all(self) -> None:
        try:
            cfg = self._read_fields_into_config()
            path = save_config(cfg)
            self.console.append(f"配置已保存：{path}")
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def _export_config(self) -> None:
        try:
            cfg = self._read_fields_into_config()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        include = messagebox.askyesnocancel(
            APP_NAME,
            "导出是否包含登录密码与镜像仓库访问令牌？\n\n"
            "选「是」：可移植明文，换机可直接导入（请妥善保管文件）\n"
            "选「否」：仅导出主机等非敏感设置\n"
            "选「取消」：放弃导出",
        )
        if include is None:
            return
        path = filedialog.asksaveasfilename(
            title="导出配置文件",
            defaultextension=".json",
            filetypes=[("配置文件", "*.json"), ("所有文件", "*.*")],
            initialfile="homeos-deploy-config.json",
        )
        if not path:
            return
        try:
            out = export_config(cfg, path, include_secrets=bool(include))
            save_config(cfg)
            self.console.append(f"已导出配置：{out}")
            messagebox.showinfo(APP_NAME, f"已导出到：\n{out}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"导出失败：{exc}")

    def _import_config(self) -> None:
        path = filedialog.askopenfilename(
            title="导入配置文件",
            filetypes=[("配置文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            APP_NAME,
            f"导入将覆盖当前界面设置，并写入本机配置：\n{config_path()}\n\n确定继续？",
        ):
            return
        try:
            cfg = import_config(path, apply_locally=True)
            self._apply_config(cfg, f"已导入配置：{path}")
            messagebox.showinfo(APP_NAME, "配置已导入并应用到表单。")
        except (OSError, ValueError, FileNotFoundError) as exc:
            messagebox.showerror(APP_NAME, f"导入失败：{exc}")

    def _clear_secrets(self) -> None:
        if not messagebox.askyesno(
            APP_NAME, "确定清除已保存的登录密码与镜像仓库访问令牌？"
        ):
            return
        try:
            e = self.steps.ssh_entries
            self.cfg.host = e["host"].get().strip()
            self.cfg.user = e["user"].get().strip()
            self.cfg.workdir = e["workdir"].get().strip()
            if self.steps.ghcr_user_entry:
                self.cfg.ghcr_user = self.steps.ghcr_user_entry.get().strip()
            port_raw = e["port"].get().strip()
            if port_raw:
                try:
                    port = int(port_raw)
                    if 1 <= port <= 65535:
                        self.cfg.port = port
                except ValueError:
                    pass
        except Exception:
            pass
        self.cfg = clear_secrets(self.cfg)
        self._set_entry(self.steps.ssh_entries["ssh_password"], "")
        if self.steps.ghcr_token_entry:
            self._set_entry(self.steps.ghcr_token_entry, "")
        if self.session.connected:
            self.controller.reset_connection_state()
            self.console.append("已清除密码；远程连接已断开。")
        else:
            self.console.append("已清除本地保存的密码与访问令牌。")

    # —— status / log / progress —— #

    def _set_status(self, connected: bool, text: str) -> None:
        self.chrome.set_status(connected, text)
        # 「连接中…」不改里程碑；仅明确离线时清除
        if not connected and text in ("未连接",):
            self.controller.mark_disconnected()
        if self._step == 2:
            self._update_deploy_checklist()

    def _on_milestones(self, milestones: Milestones) -> None:
        self.chrome.set_milestones(milestones)
        if self._step == 2:
            self._update_deploy_checklist()

    def _update_deploy_checklist(self) -> None:
        wd = self.steps.ssh_entries["workdir"].get()
        update_deploy_checklist(self.steps, self.session.connected, wd)

    def _ui_log(self, line: str) -> None:
        gen = self.console.log_gen
        self.after(0, lambda l=line, g=gen: self.console.append(l, gen=g))

    def _ui_progress(self, percent: float, detail: str = "") -> None:
        self.after(0, lambda p=percent, d=detail: set_progress(self.steps, p, d))

    def _focus_console(self) -> None:
        self.console.focus_end()

    # —— async —— #

    def _set_busy(self, busy: bool) -> None:
        self.controller.busy = busy
        self.chrome.set_busy(busy)
        self.action_bar.set_busy(busy)
        if not busy:
            self.chrome.btn_disconnect.configure(
                state="normal" if self.session.connected else "disabled"
            )
        else:
            self.chrome.btn_disconnect.configure(state="disabled")
        state = "disabled" if busy else "normal"
        for btn in self._factory.action_btns:
            try:
                btn.configure(state=state)
            except Exception:
                pass

    def _run_async(
        self,
        title: str,
        work: Callable[[], None],
        *,
        on_success: Optional[Callable[[], None]] = None,
    ) -> None:
        if self.controller.busy:
            messagebox.showwarning(APP_NAME, "已有操作在进行中，请先等待或取消。")
            return

        self._set_busy(True)
        self.console.append(f"—— {title} ——")

        def runner() -> None:
            ok = False
            try:
                work()
                ok = True
            except InterruptedError:
                self._ui_log("操作已取消。")
            except Exception as exc:
                self._ui_log(f"错误：{exc}")
                self.after(0, lambda e=str(exc): messagebox.showerror(APP_NAME, e))
            finally:

                def finish() -> None:
                    self._set_busy(False)
                    if not self.session.connected:
                        try:
                            text = self.chrome.status_label.cget("text")
                        except Exception:
                            text = ""
                        if text in ("连接中…", "连接中...", "未连接"):
                            self._set_status(False, "未连接")
                    if ok and on_success:
                        on_success()

                self.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _disconnect(self) -> None:
        if self.controller.busy:
            messagebox.showwarning(APP_NAME, "操作进行中，请先取消后再断开。")
            return
        self.controller.disconnect()

    def _cancel_op(self) -> None:
        self.controller.cancel()

    # —— actions —— #

    def _test_connect(self) -> None:
        cfg = self._snapshot_cfg_or_warn()
        if cfg is None:
            return
        missing = self.controller.ssh_missing_fields(cfg)
        if missing:
            messagebox.showwarning(
                APP_NAME, "请先填写：" + "、".join(missing) + "。"
            )
            return

        def work() -> None:
            self.controller.test_connect(cfg)
            self.after(0, self._update_deploy_checklist)

        self._run_async("测试连接", work)

    def _do_login(self) -> None:
        cfg = self._snapshot_cfg_or_warn()
        if cfg is None:
            return
        if not cfg.ghcr_user or not cfg.ghcr_token:
            messagebox.showerror(APP_NAME, "请填写镜像仓库用户名与访问令牌。")
            return
        self._run_async("登录镜像仓库", lambda: self.controller.docker_login(cfg))

    def _do_deploy(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        if cfg.down_before_deploy:
            if cfg.down_remove_volumes:
                if not messagebox.askyesno(
                    APP_NAME,
                    "已开启「部署前先下线」且「删除数据卷」。\n\n"
                    "将先移除现有容器与网络，并删除数据卷，再拉取并启动。\n"
                    "数据卷删除后不可恢复！\n\n确定继续？",
                ):
                    return
            elif not messagebox.askyesno(
                APP_NAME,
                "已开启「部署前先下线」。\n\n"
                "将先移除现有容器与网络，再拉取并启动。\n"
                "不会删除数据卷。\n\n确定继续？",
            ):
                return
        set_progress(self.steps, 0.0, "准备部署…")

        def work() -> None:
            self.controller.deploy(cfg)
            self.after(0, self._focus_console)

        self._run_async("一键部署", work)

    def _do_ps(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return

        def work() -> None:
            self.controller.compose_ps(cfg)
            self.after(0, self._focus_console)

        self._run_async("查看状态", work)

    def _do_logs(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        service = self._selected_service()
        tail = self._selected_tail()

        def work() -> None:
            self.controller.compose_logs(cfg, service, tail)
            self.after(0, self._focus_console)

        self._run_async("查看日志", work)

    def _do_restart(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        service = self._selected_service()

        def work() -> None:
            self.controller.compose_restart(cfg, service)
            self.after(0, self._focus_console)

        self._run_async("重启服务", work)

    def _do_stop(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        service = self._selected_service()
        target = service or "全部服务"
        if not messagebox.askyesno(APP_NAME, f"确定停止容器：{target}？"):
            return

        def work() -> None:
            self.controller.compose_stop(cfg, service)
            self.after(0, self._focus_console)

        self._run_async("停止服务", work)

    def _do_down(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        if not messagebox.askyesno(
            APP_NAME,
            "确定下线全部容器？\n\n"
            "将移除容器与网络，不会删除数据卷。",
        ):
            return

        def work() -> None:
            self.controller.compose_down(cfg)
            self.after(0, self._focus_console)

        self._run_async("下线服务", work)

    def _refresh_services(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return

        def work() -> None:
            services = self.controller.refresh_services(cfg)
            self._service_names = services

            def apply() -> None:
                self._sync_service_menu_from_config()
                if self.cfg.last_service and self.cfg.last_service in self._service_names:
                    assert self.steps.service_menu and self.steps.service_manual
                    self.steps.service_menu.set(self.cfg.last_service)
                    self._set_entry(self.steps.service_manual, "")
                self._focus_console()

            self.after(0, apply)

        self._run_async("刷新服务列表", work)

    def _on_close(self) -> None:
        try:
            if self.controller.busy:
                self.session.cancel()
            save_config(self._read_fields_into_config())
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass
        self.destroy()


def run_app() -> None:
    app = HomeOSDeployApp()
    app.mainloop()
