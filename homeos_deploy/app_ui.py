"""HomeOS Deploy 四步向导界面（现代布局）。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable, Optional

import customtkinter as ctk

from homeos_deploy import __version__
from homeos_deploy.config_store import (
    AppConfig,
    clear_secrets,
    config_path,
    export_config,
    import_config,
    load_config,
    save_config,
)
from homeos_deploy.defaults import (
    APP_NAME,
)
from homeos_deploy.deploy_ops import DeployOps
from homeos_deploy.ssh_session import SSHSession
from homeos_deploy import theme as T

ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("green")

STEPS = (
    ("SSH", "连接 NAS"),
    ("Registry", "ghcr 登录"),
    ("Deploy", "拉取并启动"),
    ("Ops", "状态与日志"),
)
STEP_TITLES = (
    ("SSH 连接", "配置主机、账号与远程工作目录"),
    ("容器镜像仓库", "登录 ghcr.io，以便拉取私有镜像"),
    ("一键部署", "远程执行 compose pull 与 up"),
    ("运维查看", "查看状态、日志，或重启 / 停止服务"),
)

SERVICE_ALL = "全部服务"
TAIL_OPTIONS = ("100", "200", "500")
LOG_MAX_LINES = 4000


class HomeOSDeployApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{__version__}")
        self.geometry("1100x780")
        self.minsize(1000, 700)
        self.configure(fg_color=T.BG)

        self.cfg = load_config()
        self.session = SSHSession()
        self.ops = DeployOps(self.session)
        self._step = 0
        self._busy = False
        self._log_lines: list[str] = []
        self._step_btns: list[ctk.CTkButton] = []
        self._action_btns: list[ctk.CTkButton] = []
        self._milestones = {
            "connected": False,
            "logged_in": False,
            "deployed": False,
        }
        self._service_names: list[str] = []
        self._conn_key: Optional[tuple[str, int, str, str]] = None
        self._copy_btn: Optional[ctk.CTkButton] = None
        self._copy_reset_after: Optional[str] = None

        self._build_layout()
        self._load_fields_from_config()
        self._show_step(0)
        self._set_status(False, "未连接")
        if self.cfg.is_empty():
            self._append_log("首次运行：参数为空。请手动填写，或通过左侧「导入配置」载入 JSON。")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # —— helpers —— #

    def _font(self, size: int = 13, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family=T.FONT_UI, size=size, weight=weight)

    def _mono(self, size: int = 12) -> ctk.CTkFont:
        try:
            return ctk.CTkFont(family=T.FONT_MONO, size=size)
        except Exception:
            return ctk.CTkFont(family="Consolas", size=size)

    def _primary_btn(self, parent, text: str, command, width: int = 128) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=36,
            corner_radius=10,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color="#FFFFFF",
            font=self._font(13, "bold"),
        )
        self._action_btns.append(btn)
        return btn

    def _secondary_btn(self, parent, text: str, command, width: int = 110) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=36,
            corner_radius=10,
            fg_color=T.SURFACE_MUTED,
            hover_color=T.SURFACE_HOVER,
            text_color=T.TEXT,
            border_width=1,
            border_color=T.SURFACE_BORDER,
            font=self._font(13),
        )
        self._action_btns.append(btn)
        return btn

    def _danger_btn(self, parent, text: str, command, width: int = 110) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=36,
            corner_radius=10,
            fg_color=T.DANGER_SOFT,
            hover_color=T.DANGER_SOFT_HOVER,
            text_color=T.DANGER,
            border_width=1,
            border_color="#F5C2CE",
            font=self._font(13),
        )
        self._action_btns.append(btn)
        return btn

    def _ghost_btn(self, parent, text: str, command, width: int = 88) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=T.SIDEBAR_HOVER,
            text_color=T.MUTED_ON_DARK,
            font=self._font(12),
        )

    def _field_block(
        self,
        parent,
        row: int,
        label: str,
        show: str | None = None,
        placeholder: str = "",
        column: int = 0,
        columnspan: int = 1,
        padx: tuple[int, int] | int = 0,
    ) -> ctk.CTkEntry:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="ew",
            padx=padx,
            pady=(0, 14),
        )
        wrap.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            wrap,
            text=label,
            anchor="w",
            text_color=T.MUTED,
            font=self._font(12),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        entry = ctk.CTkEntry(
            wrap,
            height=40,
            corner_radius=10,
            border_width=1,
            border_color=T.SURFACE_BORDER,
            fg_color=T.SURFACE_MUTED,
            text_color=T.TEXT,
            font=self._font(13),
            show=show,
            placeholder_text=placeholder,
        )
        entry.grid(row=1, column=0, sticky="ew")
        return entry

    def _tip_bar(self, parent, text: str, row: int = 0) -> ctk.CTkFrame:
        bar = ctk.CTkFrame(parent, fg_color=T.ACCENT_SOFT, corner_radius=10)
        ctk.CTkLabel(
            bar,
            text=text,
            text_color=T.ACCENT_HOVER,
            anchor="w",
            font=self._font(12),
        ).pack(anchor="w", padx=14, pady=10)
        bar.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        return bar

    # —— layout —— #

    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, fg_color=T.SIDEBAR, corner_radius=0, width=220)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(3, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(28, 8))
        ctk.CTkLabel(
            brand,
            text="HomeOS",
            anchor="w",
            text_color=T.TEXT_ON_DARK,
            font=self._font(26, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="Deploy Wizard",
            anchor="w",
            text_color=T.BRAND_SUB,
            font=self._font(13),
        ).pack(anchor="w", pady=(2, 0))

        status_wrap = ctk.CTkFrame(sidebar, fg_color="transparent")
        status_wrap.grid(row=1, column=0, sticky="ew", padx=16, pady=(16, 8))
        status_wrap.grid_columnconfigure(0, weight=1)

        self.status_chip = ctk.CTkFrame(
            status_wrap, fg_color=T.SIDEBAR_RAISED, corner_radius=10, height=40
        )
        self.status_chip.grid(row=0, column=0, sticky="ew")
        self.status_chip.grid_columnconfigure(1, weight=1)
        self.status_dot = ctk.CTkLabel(
            self.status_chip, text="●", text_color=T.IDLE, width=18, font=self._font(12)
        )
        self.status_dot.grid(row=0, column=0, padx=(12, 4), pady=10)
        self.status_label = ctk.CTkLabel(
            self.status_chip,
            text="未连接",
            anchor="w",
            text_color=T.MUTED_ON_DARK,
            font=self._font(12),
        )
        self.status_label.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=10)

        self.btn_disconnect = ctk.CTkButton(
            status_wrap,
            text="断开",
            width=56,
            height=40,
            corner_radius=10,
            fg_color=T.SIDEBAR_BTN,
            hover_color=T.SIDEBAR_BTN_HOVER,
            border_width=1,
            border_color=T.SIDEBAR_BTN_BORDER,
            text_color=T.MUTED_ON_DARK,
            font=self._font(12),
            command=self._disconnect,
            state="disabled",
        )
        self.btn_disconnect.grid(row=0, column=1, padx=(8, 0))

        steps_wrap = ctk.CTkFrame(sidebar, fg_color="transparent")
        steps_wrap.grid(row=2, column=0, sticky="ew", padx=12, pady=(20, 8))
        for i, (name, desc) in enumerate(STEPS):
            btn = ctk.CTkButton(
                steps_wrap,
                text=f"  {i + 1}  {name}\n      {desc}",
                anchor="w",
                height=56,
                corner_radius=10,
                fg_color="transparent",
                hover_color=T.SIDEBAR_HOVER,
                text_color=T.MUTED_ON_DARK,
                font=self._font(13),
                command=lambda idx=i: self._try_show_step(idx),
            )
            btn.pack(fill="x", pady=3)
            self._step_btns.append(btn)

        side_actions = ctk.CTkFrame(sidebar, fg_color="transparent")
        side_actions.grid(row=4, column=0, sticky="ew", padx=16, pady=(8, 10))
        side_actions.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            side_actions,
            text="导入配置",
            height=34,
            corner_radius=8,
            fg_color=T.SIDEBAR_BTN,
            hover_color=T.SIDEBAR_BTN_HOVER,
            border_width=1,
            border_color=T.SIDEBAR_BTN_BORDER,
            text_color=T.TEXT_ON_DARK,
            font=self._font(12),
            command=self._import_config,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ctk.CTkButton(
            side_actions,
            text="导出配置",
            height=34,
            corner_radius=8,
            fg_color=T.SIDEBAR_BTN,
            hover_color=T.SIDEBAR_BTN_HOVER,
            border_width=1,
            border_color=T.SIDEBAR_BTN_BORDER,
            text_color=T.TEXT_ON_DARK,
            font=self._font(12),
            command=self._export_config,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        nav = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav.grid(row=5, column=0, sticky="ew", padx=16, pady=(4, 24))
        nav.grid_columnconfigure((0, 1), weight=1)
        self.btn_prev = ctk.CTkButton(
            nav,
            text="上一步",
            height=36,
            corner_radius=10,
            fg_color=T.SIDEBAR_BTN,
            hover_color=T.SIDEBAR_BTN_HOVER,
            border_width=1,
            border_color=T.SIDEBAR_BTN_BORDER,
            text_color=T.TEXT_ON_DARK,
            font=self._font(13),
            command=self._prev_step,
        )
        self.btn_prev.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.btn_next = ctk.CTkButton(
            nav,
            text="下一步",
            command=self._next_step,
            width=90,
            height=36,
            corner_radius=10,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color="#FFFFFF",
            font=self._font(13, "bold"),
        )
        self.btn_next.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # 右侧主区：表单与控制台可伸缩
        self.main = ctk.CTkFrame(self, fg_color=T.BG, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=3)
        self.main.grid_rowconfigure(2, weight=2)

        top = ctk.CTkFrame(self.main, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=T.PAD, pady=(22, 6))
        top.grid_columnconfigure(0, weight=1)
        self.step_title = ctk.CTkLabel(
            top, text="", anchor="w", text_color=T.TEXT, font=self._font(24, "bold")
        )
        self.step_title.grid(row=0, column=0, sticky="w")
        self.step_subtitle = ctk.CTkLabel(
            top, text="", anchor="w", text_color=T.MUTED, font=self._font(13)
        )
        self.step_subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.content = ctk.CTkFrame(
            self.main,
            fg_color=T.SURFACE,
            corner_radius=T.RADIUS,
            border_width=1,
            border_color=T.SURFACE_BORDER,
        )
        self.content.grid(row=1, column=0, sticky="nsew", padx=T.PAD, pady=(6, 12))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.frames: dict[int, ctk.CTkFrame] = {}
        self.frames[0] = self._build_step_ssh(self.content)
        self.frames[1] = self._build_step_ghcr(self.content)
        self.frames[2] = self._build_step_deploy(self.content)
        self.frames[3] = self._build_step_ops(self.content)

        self.log_frame = ctk.CTkFrame(
            self.main,
            fg_color=T.TERM_BG,
            corner_radius=T.RADIUS,
            border_width=1,
            border_color=T.TERM_BORDER,
        )
        self.log_frame.grid(row=2, column=0, sticky="nsew", padx=T.PAD, pady=(0, T.PAD))
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        log_hdr = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        log_hdr.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
        log_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            log_hdr,
            text="CONSOLE",
            anchor="w",
            text_color=T.TERM_LABEL,
            font=self._mono(11),
        ).grid(row=0, column=0, sticky="w")
        self.btn_cancel = ctk.CTkButton(
            log_hdr,
            text="取消",
            width=64,
            height=28,
            corner_radius=8,
            fg_color="transparent",
            hover_color=T.SIDEBAR_HOVER,
            text_color=T.MUTED_ON_DARK,
            font=self._font(12),
            command=self._cancel_op,
            state="disabled",
        )
        self.btn_cancel.grid(row=0, column=1, padx=4)
        self._copy_btn = self._ghost_btn(log_hdr, "复制", self._copy_log, 56)
        self._copy_btn.grid(row=0, column=2, padx=2)
        self._ghost_btn(log_hdr, "清空", self._clear_log, 56).grid(row=0, column=3)

        self.log_box = ctk.CTkTextbox(
            self.log_frame,
            corner_radius=8,
            fg_color=T.TERM_BG,
            text_color=T.TERM_FG,
            border_width=0,
            font=self._mono(12),
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.log_box.configure(state="disabled")

    def _build_step_ssh(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)

        body = ctk.CTkFrame(f, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew", padx=28, pady=22)
        body.grid_columnconfigure((0, 1), weight=1)

        self.first_run_tip = self._tip_bar(
            body, "首次使用：表单为空，可点左侧「导入配置」载入 JSON。"
        )

        self.ssh_entries: dict[str, ctk.CTkEntry] = {}
        self.ssh_entries["host"] = self._field_block(
            body, 1, "主机 Host", column=0, padx=(0, 10)
        )
        self.ssh_entries["port"] = self._field_block(
            body, 1, "端口 Port", column=1, padx=(10, 0)
        )
        self.ssh_entries["user"] = self._field_block(
            body, 2, "用户 User", column=0, padx=(0, 10)
        )
        self.ssh_entries["ssh_password"] = self._field_block(
            body, 2, "密码 Password", show="*", column=1, padx=(10, 0)
        )
        self.ssh_entries["workdir"] = self._field_block(
            body,
            3,
            "远程目录 Workdir",
            column=0,
            columnspan=2,
        )

        self.config_path_label = ctk.CTkLabel(
            body,
            text=f"本机配置 · {config_path()}",
            text_color=T.MUTED,
            wraplength=780,
            justify="left",
            anchor="w",
            font=self._font(11),
        )
        self.config_path_label.grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 12))

        btns = ctk.CTkFrame(body, fg_color="transparent")
        btns.grid(row=5, column=0, columnspan=2, sticky="w")
        self.btn_test = self._primary_btn(btns, "测试连接", self._test_connect, 120)
        self.btn_test.pack(side="left", padx=(0, 8))
        self.btn_save_ssh = self._secondary_btn(btns, "保存配置", self._save_all, 110)
        self.btn_save_ssh.pack(side="left", padx=4)
        self.btn_clear_secrets = self._secondary_btn(btns, "清除密码", self._clear_secrets, 110)
        self.btn_clear_secrets.pack(side="left", padx=4)
        return f

    def _build_step_ghcr(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)

        form = ctk.CTkFrame(f, fg_color="transparent")
        form.grid(row=0, column=0, sticky="ew", padx=28, pady=28)
        form.grid_columnconfigure(0, weight=1)

        self.ghcr_ssh_tip = self._tip_bar(
            form, "建议先完成 SSH 测试连接；登录时会使用同一密码执行 sudo docker login。"
        )

        self.ghcr_user_entry = self._field_block(
            form, 1, "ghcr 用户名"
        )
        self.ghcr_token_entry = self._field_block(form, 2, "ghcr Token", show="*")

        tip = ctk.CTkLabel(
            form,
            text="本机保存使用 DPAPI 加密；导出文件可为明文，请妥善保管。未填写也可进入部署，但私有镜像会拉取失败。",
            text_color=T.MUTED,
            wraplength=640,
            justify="left",
            font=self._font(12),
        )
        tip.grid(row=3, column=0, sticky="w", pady=(0, 16))

        btns = ctk.CTkFrame(form, fg_color="transparent")
        btns.grid(row=4, column=0, sticky="w")
        self.btn_login = self._primary_btn(btns, "执行 docker login", self._do_login, 168)
        self.btn_login.pack(side="left", padx=(0, 8))
        self.btn_save_ghcr = self._secondary_btn(btns, "保存配置", self._save_all, 110)
        self.btn_save_ghcr.pack(side="left")
        return f

    def _build_step_deploy(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)

        body = ctk.CTkFrame(f, fg_color="transparent")
        body.grid(row=0, column=0, sticky="ew", padx=28, pady=28)
        body.grid_columnconfigure(0, weight=1)

        checklist = ctk.CTkFrame(
            body,
            fg_color=T.SURFACE_MUTED,
            corner_radius=12,
            border_width=1,
            border_color=T.SURFACE_BORDER,
        )
        checklist.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        ctk.CTkLabel(
            checklist,
            text="部署前检查",
            text_color=T.MUTED,
            font=self._font(12),
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 6))
        self.deploy_check_conn = ctk.CTkLabel(
            checklist, text="○  SSH 连接", text_color=T.TEXT, anchor="w", font=self._font(13)
        )
        self.deploy_check_conn.pack(anchor="w", padx=16, pady=2)
        self.deploy_check_workdir = ctk.CTkLabel(
            checklist, text="○  工作目录", text_color=T.TEXT, anchor="w", font=self._font(13)
        )
        self.deploy_check_workdir.pack(anchor="w", padx=16, pady=2)
        self.deploy_check_hint = ctk.CTkLabel(
            checklist,
            text="开始部署时会自动校验远端目录与 compose 文件。",
            text_color=T.MUTED,
            anchor="w",
            font=self._font(12),
        )
        self.deploy_check_hint.pack(anchor="w", padx=16, pady=(6, 14))

        cmd_box = ctk.CTkFrame(
            body,
            fg_color=T.SURFACE_MUTED,
            corner_radius=12,
            border_width=1,
            border_color=T.SURFACE_BORDER,
        )
        cmd_box.grid(row=1, column=0, sticky="ew", pady=(0, 18))
        ctk.CTkLabel(
            cmd_box,
            text="REMOTE COMMANDS",
            text_color=T.ACCENT,
            font=self._mono(11),
            anchor="w",
        ).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            cmd_box,
            text="docker compose pull --progress=plain\ndocker compose up -d --progress=plain",
            justify="left",
            anchor="w",
            text_color=T.TEXT,
            font=self._mono(13),
        ).pack(anchor="w", padx=16, pady=(0, 8))
        self.deploy_workdir_hint = ctk.CTkLabel(
            cmd_box, text="", text_color=T.MUTED, anchor="w", font=self._font(12)
        )
        self.deploy_workdir_hint.pack(anchor="w", padx=16, pady=(0, 14))

        prog_head = ctk.CTkFrame(body, fg_color="transparent")
        prog_head.grid(row=2, column=0, sticky="ew")
        prog_head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            prog_head, text="部署进度", text_color=T.MUTED, font=self._font(12), anchor="w"
        ).grid(row=0, column=0, sticky="w")
        self.deploy_progress_label = ctk.CTkLabel(
            prog_head,
            text="0.0%",
            width=64,
            anchor="e",
            text_color=T.TEXT,
            font=self._mono(14),
        )
        self.deploy_progress_label.grid(row=0, column=1, sticky="e")

        self.deploy_progress = ctk.CTkProgressBar(
            body,
            height=14,
            corner_radius=8,
            progress_color=T.ACCENT,
            fg_color=T.PROGRESS_TRACK,
        )
        self.deploy_progress.grid(row=3, column=0, sticky="ew", pady=(8, 6))
        self.deploy_progress.set(0)

        self.deploy_progress_detail = ctk.CTkLabel(
            body, text="等待部署…", text_color=T.MUTED, anchor="w", font=self._font(12)
        )
        self.deploy_progress_detail.grid(row=4, column=0, sticky="w", pady=(0, 18))

        self.btn_deploy = self._primary_btn(body, "开始部署", self._do_deploy, 140)
        self.btn_deploy.grid(row=5, column=0, sticky="w")
        return f

    def _build_step_ops(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid_columnconfigure(0, weight=1)

        form = ctk.CTkFrame(f, fg_color="transparent")
        form.grid(row=0, column=0, sticky="ew", padx=28, pady=28)
        form.grid_columnconfigure(0, weight=1)

        tip = self._tip_bar(
            form, "运维结果输出在下方 CONSOLE。危险操作（停止 / 下线）会二次确认。"
        )
        tip.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        svc_wrap = ctk.CTkFrame(form, fg_color="transparent")
        svc_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        svc_wrap.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            svc_wrap,
            text="Service",
            anchor="w",
            text_color=T.MUTED,
            font=self._font(12),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        svc_row = ctk.CTkFrame(svc_wrap, fg_color="transparent")
        svc_row.grid(row=1, column=0, sticky="ew")
        svc_row.grid_columnconfigure(0, weight=1)

        self.service_menu = ctk.CTkOptionMenu(
            svc_row,
            values=[SERVICE_ALL],
            height=40,
            corner_radius=10,
            fg_color=T.SURFACE_MUTED,
            button_color=T.SURFACE_HOVER,
            button_hover_color=T.SURFACE_BORDER,
            text_color=T.TEXT,
            dropdown_fg_color=T.SURFACE,
            dropdown_hover_color=T.SURFACE_HOVER,
            dropdown_text_color=T.TEXT,
            font=self._font(13),
            anchor="w",
        )
        self.service_menu.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.service_menu.set(SERVICE_ALL)

        self.btn_refresh_services = self._secondary_btn(
            svc_row, "刷新列表", self._refresh_services, 110
        )
        self.btn_refresh_services.grid(row=0, column=1)

        self.service_manual = self._field_block(
            form,
            2,
            "手动指定服务（可选，优先于上方下拉）",
            placeholder="留空则使用下拉选择",
        )

        tail_wrap = ctk.CTkFrame(form, fg_color="transparent")
        tail_wrap.grid(row=3, column=0, sticky="ew", pady=(0, 18))
        ctk.CTkLabel(
            tail_wrap,
            text="日志行数 tail",
            anchor="w",
            text_color=T.MUTED,
            font=self._font(12),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.tail_menu = ctk.CTkOptionMenu(
            tail_wrap,
            values=list(TAIL_OPTIONS),
            width=120,
            height=36,
            corner_radius=10,
            fg_color=T.SURFACE_MUTED,
            button_color=T.SURFACE_HOVER,
            button_hover_color=T.SURFACE_BORDER,
            text_color=T.TEXT,
            dropdown_fg_color=T.SURFACE,
            dropdown_hover_color=T.SURFACE_HOVER,
            dropdown_text_color=T.TEXT,
            font=self._font(13),
        )
        self.tail_menu.grid(row=1, column=0, sticky="w")
        self.tail_menu.set("200")

        btns = ctk.CTkFrame(form, fg_color="transparent")
        btns.grid(row=4, column=0, sticky="w")
        self.btn_ps = self._primary_btn(btns, "状态 ps", self._do_ps, 110)
        self.btn_ps.pack(side="left", padx=(0, 8))
        self.btn_logs = self._secondary_btn(btns, "日志 logs", self._do_logs, 110)
        self.btn_logs.pack(side="left", padx=(0, 8))
        self.btn_restart = self._secondary_btn(btns, "重启", self._do_restart, 90)
        self.btn_restart.pack(side="left", padx=(0, 8))
        self.btn_stop = self._danger_btn(btns, "停止", self._do_stop, 90)
        self.btn_stop.pack(side="left", padx=(0, 8))
        self.btn_down = self._danger_btn(btns, "下线 down", self._do_down, 110)
        self.btn_down.pack(side="left")

        help_lbl = ctk.CTkLabel(
            form,
            text="停止：停止容器但保留编排；下线 down：移除容器与网络（不删数据卷）。刷新失败时可手动输入服务名。",
            text_color=T.MUTED,
            wraplength=700,
            justify="left",
            anchor="w",
            font=self._font(12),
        )
        help_lbl.grid(row=5, column=0, sticky="w", pady=(16, 0))
        return f

    # —— step navigation —— #

    def _milestone_for_step(self, idx: int) -> bool:
        if idx == 0:
            return self._milestones["connected"]
        if idx == 1:
            return self._milestones["logged_in"]
        if idx == 2:
            return self._milestones["deployed"]
        return self._milestones["deployed"] or self._milestones["connected"]

    def _refresh_step_styles(self) -> None:
        for i, btn in enumerate(self._step_btns):
            done = self._milestone_for_step(i)
            if i == self._step:
                btn.configure(fg_color=T.SIDEBAR_RAISED, text_color=T.TEXT_ON_DARK)
            elif done:
                btn.configure(fg_color=T.SIDEBAR_DONE, text_color=T.SIDEBAR_DONE_TEXT)
            else:
                btn.configure(fg_color="transparent", text_color=T.MUTED_ON_DARK)

    def _update_deploy_checklist(self) -> None:
        if not hasattr(self, "deploy_check_conn"):
            return
        conn_ok = self.session.connected
        wd = self.ssh_entries["workdir"].get().strip() or self.cfg.workdir
        self.deploy_check_conn.configure(
            text=("●  SSH 已连接" if conn_ok else "○  SSH 未连接"),
            text_color=T.SUCCESS if conn_ok else T.TEXT,
        )
        self.deploy_check_workdir.configure(
            text=(f"●  工作目录  {wd}" if wd else "○  工作目录未填写"),
            text_color=T.SUCCESS if wd else T.TEXT,
        )
        self.deploy_workdir_hint.configure(text=f"工作目录  {wd}" if wd else "工作目录未填写")

    def _show_step(self, idx: int) -> None:
        self._step = idx
        title, subtitle = STEP_TITLES[idx]
        self.step_title.configure(text=title)
        self.step_subtitle.configure(text=subtitle)

        for i, frame in self.frames.items():
            if i == idx:
                frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
            else:
                frame.grid_forget()

        # Ops 步加大 CONSOLE 权重
        if idx == 3:
            self.main.grid_rowconfigure(1, weight=2)
            self.main.grid_rowconfigure(2, weight=3)
        else:
            self.main.grid_rowconfigure(1, weight=3)
            self.main.grid_rowconfigure(2, weight=2)

        self.btn_prev.configure(state="normal" if idx > 0 else "disabled")
        self.btn_next.configure(state="normal" if idx < len(STEPS) - 1 else "disabled")
        if idx == 2:
            self._update_deploy_checklist()
        self._refresh_step_styles()

    def _validate_leaving_step(self, from_idx: int, to_idx: int) -> bool:
        """前进时校验途经各步字段；允许回退。"""
        if to_idx <= from_idx:
            return True
        try:
            cfg = self._read_fields_into_config()
        except ValueError as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return False

        # 跳步时按途经步骤逐项校验（含从 SSH 直接跳到 Deploy/Ops）
        for step in range(from_idx, to_idx):
            if step == 0:
                missing = []
                if not cfg.host:
                    missing.append("Host")
                if cfg.port <= 0:
                    missing.append("Port")
                if not cfg.user:
                    missing.append("User")
                if not cfg.ssh_password:
                    missing.append("Password")
                if not cfg.workdir:
                    missing.append("Workdir")
                if missing:
                    messagebox.showwarning(
                        APP_NAME,
                        "请先填写：" + "、".join(missing) + "，再进入下一步。",
                    )
                    return False
            if step == 1:
                if not cfg.ghcr_user or not cfg.ghcr_token:
                    if not messagebox.askyesno(
                        APP_NAME,
                        "尚未填写 ghcr 用户名或 Token。\n"
                        "私有镜像可能无法拉取，仍要继续？",
                    ):
                        return False
        return True

    def _try_show_step(self, idx: int) -> None:
        if self._busy:
            messagebox.showwarning(APP_NAME, "已有操作在进行中，请先等待或取消。")
            return
        if not self._validate_leaving_step(self._step, idx):
            return
        self._show_step(idx)

    def _prev_step(self) -> None:
        if self._busy:
            return
        if self._step > 0:
            self._show_step(self._step - 1)

    def _next_step(self) -> None:
        if self._busy:
            return
        if self._step < len(STEPS) - 1:
            self._try_show_step(self._step + 1)

    # —— config / fields —— #

    def _set_entry(self, entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, tk.END)
        entry.insert(0, value)

    def _selected_service(self) -> str:
        manual = self.service_manual.get().strip()
        if manual:
            return manual
        value = self.service_menu.get().strip()
        if not value or value == SERVICE_ALL:
            return ""
        return value

    def _selected_tail(self) -> int:
        try:
            return int(self.tail_menu.get())
        except ValueError:
            return 200

    def _sync_service_menu_from_config(self) -> None:
        last = self.cfg.last_service.strip()
        values = [SERVICE_ALL] + list(self._service_names)
        if last and last not in self._service_names and last not in values:
            values.append(last)
        self.service_menu.configure(values=values)
        if last and last in self._service_names:
            self.service_menu.set(last)
            self._set_entry(self.service_manual, "")
        elif last and last not in self._service_names:
            self.service_menu.set(SERVICE_ALL)
            self._set_entry(self.service_manual, last)
        else:
            self.service_menu.set(SERVICE_ALL)
            self._set_entry(self.service_manual, "")

    def _load_fields_from_config(self) -> None:
        self._set_entry(self.ssh_entries["host"], self.cfg.host)
        self._set_entry(
            self.ssh_entries["port"],
            "" if self.cfg.port <= 0 else str(self.cfg.port),
        )
        self._set_entry(self.ssh_entries["user"], self.cfg.user)
        self._set_entry(self.ssh_entries["ssh_password"], self.cfg.ssh_password)
        self._set_entry(self.ssh_entries["workdir"], self.cfg.workdir)
        self._set_entry(self.ghcr_user_entry, self.cfg.ghcr_user)
        self._set_entry(self.ghcr_token_entry, self.cfg.ghcr_token)
        self._sync_service_menu_from_config()
        if hasattr(self, "config_path_label"):
            self.config_path_label.configure(text=f"本机配置 · {config_path()}")
        if hasattr(self, "first_run_tip"):
            if self.cfg.is_empty():
                self.first_run_tip.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
            else:
                self.first_run_tip.grid_forget()

    def _read_fields_into_config(self) -> AppConfig:
        port_raw = self.ssh_entries["port"].get().strip()
        if not port_raw:
            port = 0
        else:
            try:
                port = int(port_raw)
            except ValueError as exc:
                raise ValueError("端口必须是数字。") from exc
            if port <= 0 or port > 65535:
                raise ValueError("端口必须在 1–65535 之间。")
        self.cfg.host = self.ssh_entries["host"].get().strip()
        self.cfg.port = port
        self.cfg.user = self.ssh_entries["user"].get().strip()
        self.cfg.ssh_password = self.ssh_entries["ssh_password"].get()
        self.cfg.workdir = self.ssh_entries["workdir"].get().strip()
        self.cfg.ghcr_user = self.ghcr_user_entry.get().strip()
        self.cfg.ghcr_token = self.ghcr_token_entry.get()
        self.cfg.last_service = self._selected_service()
        return self.cfg

    def _ssh_missing_fields(self, cfg: AppConfig) -> list[str]:
        missing = []
        if not cfg.host:
            missing.append("Host")
        if cfg.port <= 0:
            missing.append("Port")
        if not cfg.user:
            missing.append("User")
        if not cfg.ssh_password:
            missing.append("Password")
        return missing

    def _apply_config(self, cfg: AppConfig, note: str) -> None:
        # 导入后凭证可能变化，断开旧会话避免操作打到错误主机
        if self.session.connected:
            self.session.close()
            self._conn_key = None
            self._milestones["connected"] = False
            self._set_status(False, "未连接")
            self._append_log("已导入新配置，已断开旧 SSH 连接。")
        self.cfg = cfg
        self._service_names = []
        self._load_fields_from_config()
        self._append_log(note)

    def _save_all(self, *, quiet: bool = False) -> None:
        try:
            cfg = self._read_fields_into_config()
            path = save_config(cfg)
            self._append_log(f"配置已保存：{path}")
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
            "导出是否包含 SSH 密码与 ghcr Token？\n\n"
            "选「是」：可移植明文，换机可直接导入（请妥善保管文件）\n"
            "选「否」：仅导出主机等非敏感设置\n"
            "选「取消」：放弃导出",
        )
        if include is None:
            return

        path = filedialog.asksaveasfilename(
            title="导出配置文件",
            defaultextension=".json",
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")],
            initialfile="homeos-deploy-config.json",
        )
        if not path:
            return
        try:
            out = export_config(cfg, path, include_secrets=bool(include))
            save_config(cfg)
            self._append_log(f"已导出配置：{out}")
            messagebox.showinfo(APP_NAME, f"已导出到：\n{out}")
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"导出失败：{exc}")

    def _import_config(self) -> None:
        path = filedialog.askopenfilename(
            title="导入配置文件",
            filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")],
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
        if not messagebox.askyesno(APP_NAME, "确定清除已保存的 SSH 密码与 ghcr Token？"):
            return
        # 即使端口等字段非法，也允许清除敏感字段
        try:
            self.cfg.host = self.ssh_entries["host"].get().strip()
            self.cfg.user = self.ssh_entries["user"].get().strip()
            self.cfg.workdir = self.ssh_entries["workdir"].get().strip()
            self.cfg.ghcr_user = self.ghcr_user_entry.get().strip()
            port_raw = self.ssh_entries["port"].get().strip()
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
        self._set_entry(self.ssh_entries["ssh_password"], "")
        self._set_entry(self.ghcr_token_entry, "")
        if self.session.connected:
            self.session.close()
            self._conn_key = None
            self._set_status(False, "未连接")
            self._append_log("已清除密码；SSH 已断开。")
        else:
            self._append_log("已清除本地保存的密码与 Token。")

    # —— status / log —— #

    def _set_status(self, connected: bool, text: str) -> None:
        color = T.SUCCESS if connected else T.IDLE
        self.status_dot.configure(text_color=color)
        self.status_label.configure(text=text)
        self.btn_disconnect.configure(state="normal" if connected else "disabled")
        if not connected:
            self._milestones["connected"] = False
        self._refresh_step_styles()
        if self._step == 2:
            self._update_deploy_checklist()

    def _append_log(self, line: str) -> None:
        self._log_lines.append(line)
        if len(self._log_lines) > LOG_MAX_LINES:
            overflow = len(self._log_lines) - LOG_MAX_LINES
            self._log_lines = self._log_lines[overflow:]
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            self.log_box.insert("end", "\n".join(self._log_lines) + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
            return
        self.log_box.configure(state="normal")
        self.log_box.insert("end", line + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _clear_log(self) -> None:
        self._log_lines.clear()
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    def _copy_log(self) -> None:
        text = "\n".join(self._log_lines)
        self.clipboard_clear()
        self.clipboard_append(text)
        if self._copy_btn is not None:
            self._copy_btn.configure(text="已复制")
            if self._copy_reset_after is not None:
                try:
                    self.after_cancel(self._copy_reset_after)
                except Exception:
                    pass
            self._copy_reset_after = self.after(
                1500, lambda: self._copy_btn.configure(text="复制") if self._copy_btn else None
            )

    def _set_progress(self, percent: float, detail: str = "") -> None:
        pct = max(0.0, min(100.0, float(percent)))
        self.deploy_progress.set(pct / 100.0)
        self.deploy_progress_label.configure(text=f"{pct:5.1f}%")
        if detail:
            self.deploy_progress_detail.configure(text=detail)

    def _ui_progress(self, percent: float, detail: str = "") -> None:
        self.after(0, lambda p=percent, d=detail: self._set_progress(p, d))

    def _ui_log(self, line: str) -> None:
        self.after(0, lambda l=line: self._append_log(l))

    def _focus_console(self) -> None:
        try:
            self.log_box.focus_set()
            self.log_box.see("end")
        except Exception:
            pass

    # —— async helpers —— #

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in self._step_btns:
            try:
                widget.configure(state="disabled" if busy else "normal")
            except Exception:
                pass

        if busy:
            self.btn_prev.configure(state="disabled")
            self.btn_next.configure(state="disabled")
            self.btn_disconnect.configure(state="disabled")
        else:
            self.btn_prev.configure(state="normal" if self._step > 0 else "disabled")
            self.btn_next.configure(
                state="normal" if self._step < len(STEPS) - 1 else "disabled"
            )
            self.btn_disconnect.configure(
                state="normal" if self.session.connected else "disabled"
            )

        action_state = "disabled" if busy else "normal"
        for btn in self._action_btns:
            try:
                btn.configure(state=action_state)
            except Exception:
                pass

        try:
            if busy:
                self.btn_cancel.configure(
                    state="normal",
                    text_color=T.DANGER,
                    fg_color=T.DANGER_SOFT,
                    hover_color=T.DANGER_SOFT_HOVER,
                )
            else:
                self.btn_cancel.configure(
                    state="disabled",
                    text_color=T.MUTED_ON_DARK,
                    fg_color="transparent",
                    hover_color=T.SIDEBAR_HOVER,
                )
        except Exception:
            pass

    def _run_async(self, title: str, work: Callable[[], None]) -> None:
        if self._busy:
            messagebox.showwarning(APP_NAME, "已有操作在进行中，请先等待或取消。")
            return

        # 同步置忙，避免 after(0) 竞态导致重复启动
        self._set_busy(True)
        self._append_log(f"—— {title} ——")

        def runner() -> None:
            try:
                work()
            except InterruptedError:
                self._ui_log("操作已取消。")
            except Exception as exc:
                self._ui_log(f"错误：{exc}")
                self.after(0, lambda e=str(exc): messagebox.showerror(APP_NAME, e))
            finally:
                def finish() -> None:
                    self._set_busy(False)
                    # 测试连接失败时避免状态停留在「连接中…」
                    if not self.session.connected:
                        try:
                            text = self.status_label.cget("text")
                        except Exception:
                            text = ""
                        if text in ("连接中…", "连接中..."):
                            self._set_status(False, "未连接")

                self.after(0, finish)

        threading.Thread(target=runner, daemon=True).start()

    def _conn_identity(self, cfg: AppConfig) -> tuple[str, int, str, str]:
        return (cfg.host, cfg.port, cfg.user, cfg.ssh_password)

    def _ensure_connected(self, cfg: AppConfig) -> None:
        """使用主线程已快照的 cfg 建立/复用连接（勿在工作线程读 Tk）。"""
        missing = self._ssh_missing_fields(cfg)
        if missing:
            self.after(0, lambda: self._show_step(0))
            raise ValueError(
                "请先填写：" + "、".join(missing) + "；或通过左侧「导入配置」载入。"
            )

        key = self._conn_identity(cfg)
        if self.session.connected and self._conn_key == key:
            return

        if self.session.connected:
            self._ui_log("连接参数已变更，正在重新连接…")
            self.session.close()
            self._conn_key = None

        self._ui_log(f"正在连接 {cfg.user}@{cfg.host}:{cfg.port} ...")
        self.session.connect(cfg.host, cfg.port, cfg.user, cfg.ssh_password)
        self._conn_key = key
        self._milestones["connected"] = True
        self.after(
            0,
            lambda: self._set_status(True, f"已连接 {cfg.user}@{cfg.host}"),
        )
        self._ui_log("SSH 连接成功。")

    def _disconnect(self) -> None:
        if self._busy:
            messagebox.showwarning(APP_NAME, "操作进行中，请先取消后再断开。")
            return
        self.session.close()
        self._conn_key = None
        self._milestones["connected"] = False
        self._set_status(False, "未连接")
        self._append_log("已断开 SSH 连接。")

    def _cancel_op(self) -> None:
        self.session.cancel()
        self._append_log("已请求取消…")

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
        if not cfg.workdir:
            self._show_step(0)
            messagebox.showerror(APP_NAME, "请填写远程工作目录。")
            return None
        return cfg

    # —— actions —— #

    def _test_connect(self) -> None:
        cfg = self._snapshot_cfg_or_warn()
        if cfg is None:
            return
        missing = self._ssh_missing_fields(cfg)
        if missing:
            messagebox.showwarning(
                APP_NAME,
                "请先填写：" + "、".join(missing) + "。",
            )
            return

        def work() -> None:
            self.session.close()
            self._conn_key = None
            self.after(0, lambda: self._set_status(False, "连接中…"))
            self._ensure_connected(cfg)
            code, _out = self.session.run("pwd; uname -a", on_output=self._ui_log)
            if code != 0:
                raise RuntimeError(f"测试命令失败，退出码 {code}")
            save_config(cfg)
            self._milestones["connected"] = True
            self._ui_log("测试连接通过；配置已自动保存。")
            self.after(0, self._refresh_step_styles)
            self.after(0, self._update_deploy_checklist)

        self._run_async("测试连接", work)

    def _do_login(self) -> None:
        cfg = self._snapshot_cfg_or_warn()
        if cfg is None:
            return
        if not cfg.ghcr_user or not cfg.ghcr_token:
            messagebox.showerror(APP_NAME, "请填写 ghcr 用户名与 Token。")
            return

        def work() -> None:
            self._ensure_connected(cfg)
            code = self.ops.docker_login(
                cfg.ghcr_user,
                cfg.ghcr_token,
                cfg.ssh_password,
                on_output=self._ui_log,
            )
            if code != 0:
                raise RuntimeError(f"docker login 失败，退出码 {code}")
            self._ui_log("docker login 成功。")
            save_config(cfg)
            self._milestones["logged_in"] = True
            self.after(0, self._refresh_step_styles)

        self._run_async("docker login", work)

    def _do_deploy(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        save_config(cfg)
        self._set_progress(0.0, "准备部署…")

        def work() -> None:
            self._ensure_connected(cfg)
            self._ui_log("检查远程工作目录与 compose 文件…")
            self.ops.check_deploy_ready(
                cfg.workdir, cfg.ssh_password, on_output=self._ui_log
            )
            self._ui_log("前置检查通过。")
            code = self.ops.deploy(
                cfg.workdir,
                cfg.ssh_password,
                on_output=self._ui_log,
                on_progress=self._ui_progress,
            )
            if code != 0:
                raise RuntimeError(f"部署失败，退出码 {code}")
            self._ui_progress(100.0, "部署完成")
            self._ui_log("部署完成。")
            self._milestones["deployed"] = True
            self.after(0, self._refresh_step_styles)
            self.after(0, self._focus_console)

        self._run_async("部署 (pull + up)", work)

    def _do_ps(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        save_config(cfg)

        def work() -> None:
            self._ensure_connected(cfg)
            code = self.ops.compose_ps(cfg.workdir, cfg.ssh_password, on_output=self._ui_log)
            if code != 0:
                raise RuntimeError(f"compose ps 失败，退出码 {code}")
            self.after(0, self._focus_console)

        self._run_async("docker compose ps", work)

    def _do_logs(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        service = self._selected_service()
        tail = self._selected_tail()
        cfg.last_service = service
        save_config(cfg)

        def work() -> None:
            self._ensure_connected(cfg)
            code = self.ops.compose_logs(
                cfg.workdir,
                cfg.ssh_password,
                service=service,
                tail=tail,
                on_output=self._ui_log,
            )
            if code != 0:
                raise RuntimeError(f"compose logs 失败，退出码 {code}")
            self.after(0, self._focus_console)

        self._run_async("docker compose logs", work)

    def _do_restart(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        service = self._selected_service()
        cfg.last_service = service
        save_config(cfg)

        def work() -> None:
            self._ensure_connected(cfg)
            code = self.ops.compose_restart(
                cfg.workdir, cfg.ssh_password, service=service, on_output=self._ui_log
            )
            if code != 0:
                raise RuntimeError(f"compose restart 失败，退出码 {code}")
            self._ui_log("重启完成。")
            self.after(0, self._focus_console)

        self._run_async("docker compose restart", work)

    def _do_stop(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        service = self._selected_service()
        target = service or "全部服务"
        if not messagebox.askyesno(APP_NAME, f"确定停止容器：{target}？"):
            return
        cfg.last_service = service
        save_config(cfg)

        def work() -> None:
            self._ensure_connected(cfg)
            code = self.ops.compose_stop(
                cfg.workdir, cfg.ssh_password, service=service, on_output=self._ui_log
            )
            if code != 0:
                raise RuntimeError(f"compose stop 失败，退出码 {code}")
            self._ui_log("停止完成。")
            self.after(0, self._focus_console)

        self._run_async("docker compose stop", work)

    def _do_down(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return
        if not messagebox.askyesno(
            APP_NAME,
            "确定执行 docker compose down？\n\n"
            "将移除容器与网络，不会删除数据卷（不加 -v）。",
        ):
            return
        save_config(cfg)

        def work() -> None:
            self._ensure_connected(cfg)
            code = self.ops.compose_down(
                cfg.workdir, cfg.ssh_password, on_output=self._ui_log
            )
            if code != 0:
                raise RuntimeError(f"compose down 失败，退出码 {code}")
            self._ui_log("下线完成。")
            self.after(0, self._focus_console)

        self._run_async("docker compose down", work)

    def _refresh_services(self) -> None:
        cfg = self._require_workdir_cfg()
        if cfg is None:
            return

        def work() -> None:
            self._ensure_connected(cfg)
            services = self.ops.compose_services(
                cfg.workdir, cfg.ssh_password, on_output=self._ui_log
            )
            self._service_names = services
            self._ui_log(f"已加载 {len(services)} 个服务。")

            def apply() -> None:
                self._sync_service_menu_from_config()
                if self.cfg.last_service and self.cfg.last_service in self._service_names:
                    self.service_menu.set(self.cfg.last_service)
                    self._set_entry(self.service_manual, "")
                self._focus_console()

            self.after(0, apply)

        self._run_async("刷新服务列表", work)

    def _on_close(self) -> None:
        try:
            if self._busy:
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
