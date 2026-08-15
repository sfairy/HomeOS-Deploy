"""四步表单构建。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import customtkinter as ctk

from homeos_deploy import theme as T
from homeos_deploy.config_store import config_path
from homeos_deploy.deploy_ops import normalize_workdir
from homeos_deploy.ui.components import (
    WidgetFactory,
    field_block,
    hint_label,
    mono_font,
    option_menu,
    section_card,
    tip_bar,
    ui_font,
)
from homeos_deploy.ui.constants import SERVICE_ALL, TAIL_OPTIONS


@dataclass
class StepWidgets:
    """各步控件引用，供主窗口读写。"""

    frames: dict[int, ctk.CTkFrame] = field(default_factory=dict)
    ssh_entries: dict[str, ctk.CTkEntry] = field(default_factory=dict)
    first_run_tip: Optional[ctk.CTkFrame] = None
    config_path_label: Optional[ctk.CTkLabel] = None
    ghcr_user_entry: Optional[ctk.CTkEntry] = None
    ghcr_token_entry: Optional[ctk.CTkEntry] = None
    deploy_check_conn: Optional[ctk.CTkLabel] = None
    deploy_check_workdir: Optional[ctk.CTkLabel] = None
    deploy_progress: Optional[ctk.CTkProgressBar] = None
    deploy_progress_label: Optional[ctk.CTkLabel] = None
    deploy_progress_detail: Optional[ctk.CTkLabel] = None
    deploy_down_before: Optional[ctk.CTkCheckBox] = None
    deploy_down_volumes: Optional[ctk.CTkCheckBox] = None
    service_menu: Optional[ctk.CTkOptionMenu] = None
    service_manual: Optional[ctk.CTkEntry] = None
    tail_menu: Optional[ctk.CTkOptionMenu] = None
    ops_btn_frame: Optional[ctk.CTkFrame] = None


def build_all_steps(
    parent: ctk.CTkFrame,
    factory: WidgetFactory,
    *,
    on_clear_secrets: Callable[[], None],
    on_save: Callable[[], None],
    on_ps: Callable[[], None],
    on_logs: Callable[[], None],
    on_restart: Callable[[], None],
    on_stop: Callable[[], None],
    on_down: Callable[[], None],
    on_refresh_services: Callable[[], None],
) -> StepWidgets:
    w = StepWidgets()
    w.frames[0] = _build_ssh(parent, w, factory, on_clear_secrets, on_save)
    w.frames[1] = _build_ghcr(parent, w, factory, on_save)
    w.frames[2] = _build_deploy(parent, w)
    w.frames[3] = _build_ops(
        parent, w, factory, on_ps, on_logs, on_restart, on_stop, on_down, on_refresh_services
    )
    return w


def _shell(parent: ctk.CTkFrame) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
    shell = ctk.CTkFrame(parent, fg_color="transparent")
    shell.grid_columnconfigure(0, weight=1)
    shell.grid_rowconfigure(0, weight=0)
    body = ctk.CTkFrame(shell, fg_color="transparent")
    # 贴合内容高度，无滚动条
    body.grid(row=0, column=0, sticky="ew", padx=14, pady=(6, 4))
    body.grid_columnconfigure(0, weight=1)
    return shell, body


def _build_ssh(
    parent: ctk.CTkFrame,
    w: StepWidgets,
    factory: WidgetFactory,
    on_clear_secrets: Callable[[], None],
    on_save: Callable[[], None],
) -> ctk.CTkFrame:
    shell, body = _shell(parent)
    body.grid_columnconfigure((0, 1), weight=1)

    w.first_run_tip = tip_bar(
        body, "首次运行表单为空 — 请手动填写，或使用左侧「导入配置」载入。"
    )
    w.first_run_tip.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))

    w.ssh_entries["host"] = field_block(body, 1, "主机", column=0, padx=(0, 8))
    w.ssh_entries["port"] = field_block(body, 1, "端口", column=1, padx=(8, 0))
    w.ssh_entries["user"] = field_block(body, 2, "用户名", column=0, padx=(0, 8))
    w.ssh_entries["ssh_password"] = field_block(
        body, 2, "密码", column=1, padx=(8, 0), show="•"
    )
    w.ssh_entries["workdir"] = field_block(
        body, 3, "工作目录（远端绝对路径）", column=0, columnspan=2
    )

    extras = ctk.CTkFrame(body, fg_color="transparent")
    extras.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
    extras.grid_columnconfigure(0, weight=1)
    factory.danger(extras, "清除密码", on_clear_secrets, 100).pack(side="left")
    factory.secondary(extras, "保存配置", on_save, 100).pack(side="right")

    w.config_path_label = ctk.CTkLabel(
        body,
        text=f"本机配置 · {config_path()}",
        anchor="w",
        text_color=T.MUTED,
        font=ui_font(10),
    )
    w.config_path_label.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 0))
    return shell


def _build_ghcr(
    parent: ctk.CTkFrame,
    w: StepWidgets,
    factory: WidgetFactory,
    on_save: Callable[[], None],
) -> ctk.CTkFrame:
    shell, body = _shell(parent)
    body.grid_columnconfigure((0, 1), weight=1)

    tip_bar(
        body, "登录镜像仓库后即可拉取私有镜像。令牌需具备软件包读取权限。"
    ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

    w.ghcr_user_entry = field_block(body, 1, "仓库用户名", column=0, padx=(0, 8))
    w.ghcr_token_entry = field_block(
        body, 1, "访问令牌", column=1, padx=(8, 0), show="•"
    )

    footer = ctk.CTkFrame(body, fg_color="transparent")
    footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
    footer.grid_columnconfigure(0, weight=1)

    hint_label(
        footer, "建议先完成远程连接测试。远端容器命令默认经管理员权限执行。"
    ).grid(row=0, column=0, sticky="w", padx=(0, 12))

    factory.secondary(footer, "保存配置", on_save, 100).grid(
        row=0, column=1, sticky="e"
    )
    return shell


def _build_deploy(parent: ctk.CTkFrame, w: StepWidgets) -> ctk.CTkFrame:
    shell, body = _shell(parent)
    body.grid_columnconfigure((0, 1), weight=1)

    tip_bar(
        body, "将远程拉取镜像并后台启动容器。部署前会自动校验工作目录与编排文件。"
    ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

    check_card, check_body = section_card(body, "部署前检查")
    check_card.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
    w.deploy_check_conn = ctk.CTkLabel(
        check_body, text="○  远程未连接", anchor="w", text_color=T.TEXT, font=ui_font(13)
    )
    w.deploy_check_conn.pack(anchor="w", pady=(0, 8))
    w.deploy_check_workdir = ctk.CTkLabel(
        check_body, text="○  工作目录未填写", anchor="w", text_color=T.TEXT, font=ui_font(13)
    )
    w.deploy_check_workdir.pack(anchor="w")

    prog_card, prog_body = section_card(body, "部署进度")
    prog_card.grid(row=1, column=1, sticky="nsew", padx=(8, 0))
    row = ctk.CTkFrame(prog_body, fg_color="transparent")
    row.pack(fill="x")
    row.grid_columnconfigure(0, weight=1)
    w.deploy_progress = ctk.CTkProgressBar(
        row,
        height=14,
        corner_radius=7,
        progress_color=T.ACCENT,
        fg_color=T.PROGRESS_TRACK,
    )
    w.deploy_progress.grid(row=0, column=0, sticky="ew", padx=(0, 10))
    w.deploy_progress.set(0)
    w.deploy_progress_label = ctk.CTkLabel(
        row, text="0.0%", width=56, text_color=T.ACCENT, font=ui_font(12)
    )
    w.deploy_progress_label.grid(row=0, column=1)
    w.deploy_progress_detail = ctk.CTkLabel(
        prog_body,
        text="等待开始…",
        anchor="w",
        text_color=T.MUTED,
        font=ui_font(11),
        wraplength=320,
    )
    w.deploy_progress_detail.pack(anchor="w", pady=(10, 0))

    opt_card, opt_body = section_card(body, "部署选项")
    opt_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
    opt_body.grid_columnconfigure(0, weight=1)
    opt_body.grid_columnconfigure(1, weight=1)

    def _sync_volume_switch() -> None:
        if w.deploy_down_volumes is None or w.deploy_down_before is None:
            return
        if w.deploy_down_before.get():
            w.deploy_down_volumes.configure(state="normal")
        else:
            w.deploy_down_volumes.deselect()
            w.deploy_down_volumes.configure(state="disabled")

    w.deploy_down_before = ctk.CTkCheckBox(
        opt_body,
        text="部署前先下线旧容器",
        font=ui_font(12),
        text_color=T.TEXT_DIM,
        fg_color=T.ACCENT,
        hover_color=T.ACCENT_HOVER,
        border_color=T.SURFACE_BORDER,
        checkmark_color="#041018",
        command=_sync_volume_switch,
    )
    w.deploy_down_before.grid(row=0, column=0, sticky="w", padx=(0, 12))

    w.deploy_down_volumes = ctk.CTkCheckBox(
        opt_body,
        text="同时删除数据卷（危险，不可恢复）",
        font=ui_font(12),
        text_color=T.DANGER,
        fg_color=T.DANGER,
        hover_color=T.DANGER_SOFT_HOVER,
        border_color=T.SURFACE_BORDER,
        checkmark_color="#041018",
        state="disabled",
    )
    w.deploy_down_volumes.grid(row=0, column=1, sticky="w")
    return shell


def _build_ops(
    parent: ctk.CTkFrame,
    w: StepWidgets,
    factory: WidgetFactory,
    on_ps: Callable[[], None],
    on_logs: Callable[[], None],
    on_restart: Callable[[], None],
    on_stop: Callable[[], None],
    on_down: Callable[[], None],
    on_refresh_services: Callable[[], None],
) -> ctk.CTkFrame:
    shell, body = _shell(parent)
    body.grid_columnconfigure((0, 1), weight=1)

    tip_bar(
        body, "查看容器状态与日志，或对单个服务重启 / 停止。下线默认不删除数据卷。"
    ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

    svc_wrap = ctk.CTkFrame(body, fg_color="transparent")
    svc_wrap.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, T.FIELD_GAP))
    svc_wrap.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(
        svc_wrap, text="服务", anchor="w", text_color=T.MUTED, font=ui_font(11)
    ).grid(row=0, column=0, sticky="w")
    row = ctk.CTkFrame(svc_wrap, fg_color="transparent")
    row.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    row.grid_columnconfigure(0, weight=1)
    w.service_menu = option_menu(row, [SERVICE_ALL])
    w.service_menu.grid(row=0, column=0, sticky="ew", padx=(0, 6))
    w.service_menu.set(SERVICE_ALL)
    factory.secondary(row, "刷新", on_refresh_services, 72).grid(row=0, column=1)

    tail_wrap = ctk.CTkFrame(body, fg_color="transparent")
    tail_wrap.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, T.FIELD_GAP))
    ctk.CTkLabel(
        tail_wrap, text="日志行数", anchor="w", text_color=T.MUTED, font=ui_font(11)
    ).pack(anchor="w")
    w.tail_menu = option_menu(tail_wrap, TAIL_OPTIONS, width=120)
    w.tail_menu.pack(anchor="w", pady=(4, 0))
    w.tail_menu.set("200")

    w.service_manual = field_block(
        body, 2, "手动服务名（可选，优先于下拉）", column=0, columnspan=2
    )

    actions = ctk.CTkFrame(body, fg_color="transparent")
    actions.grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
    w.ops_btn_frame = actions
    factory.secondary(actions, "查看状态", on_ps, 88).pack(side="left", padx=(0, 6))
    factory.secondary(actions, "查看日志", on_logs, 88).pack(side="left", padx=(0, 6))
    factory.secondary(actions, "重启", on_restart, 72).pack(side="left", padx=(0, 6))
    factory.danger(actions, "停止", on_stop, 72).pack(side="left", padx=(0, 6))
    factory.danger(actions, "下线", on_down, 72).pack(side="left")
    return shell


def update_deploy_checklist(w: StepWidgets, connected: bool, workdir_raw: str) -> None:
    if not w.deploy_check_conn:
        return
    wd = normalize_workdir(workdir_raw)
    w.deploy_check_conn.configure(
        text=("●  远程已连接" if connected else "○  远程未连接"),
        text_color=T.SUCCESS if connected else T.TEXT,
    )
    w.deploy_check_workdir.configure(
        text=(f"●  工作目录  {wd}" if wd else "○  工作目录未填写"),
        text_color=T.SUCCESS if wd else T.TEXT,
    )


def set_progress(w: StepWidgets, percent: float, detail: str = "") -> None:
    if not w.deploy_progress:
        return
    pct = max(0.0, min(100.0, float(percent)))
    w.deploy_progress.set(pct / 100.0)
    if w.deploy_progress_label:
        w.deploy_progress_label.configure(text=f"{pct:5.1f}%")
    if w.deploy_progress_detail:
        text = detail.strip() if detail else "…"
        if text and not text.endswith("%") and pct > 0:
            # 详情里带上当前百分比，避免只显示「拉取镜像」看不出变化
            if text in ("拉取镜像", "启动容器", "准备部署…", "检查工作目录…"):
                text = f"{text}  ·  {pct:.0f}%"
        w.deploy_progress_detail.configure(text=text)
