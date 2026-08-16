"""窄侧栏：品牌、连接状态、纵向步进器、导入/导出（Aether Dock）。"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from homeos_deploy import __version__
from homeos_deploy import theme as T
from homeos_deploy.app_controller import Milestones
from homeos_deploy.defaults import COPYRIGHT_DEVELOPER, COPYRIGHT_HOLDER
from homeos_deploy.ui.components import mono_font, ui_font
from homeos_deploy.ui.constants import STEPS


class SlimSidebar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_step: Callable[[int], None],
        on_disconnect: Callable[[], None],
        on_import: Callable[[], None],
        on_export: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=T.HEADER,
            corner_radius=0,
            width=T.SIDEBAR_WIDTH,
            **kwargs,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._on_step = on_step
        self._current = 0
        self._milestones = Milestones()
        self._busy = False
        self._dots: list[ctk.CTkLabel] = []
        self._name_labels: list[ctk.CTkLabel] = []
        self._desc_labels: list[ctk.CTkLabel] = []
        self._rows: list[ctk.CTkFrame] = []
        self._row_style: list[str] = []

        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(20, 6))
        ctk.CTkLabel(
            brand,
            text="HomeOS",
            anchor="w",
            text_color=T.BRAND,
            font=ui_font(20, "bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="部署向导",
            anchor="w",
            text_color=T.BRAND_SUB,
            font=ui_font(11),
        ).pack(anchor="w", pady=(2, 0))

        status_wrap = ctk.CTkFrame(self, fg_color="transparent")
        status_wrap.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 4))
        status_wrap.grid_columnconfigure(0, weight=1)

        self.status_chip = ctk.CTkFrame(
            status_wrap,
            fg_color=T.SURFACE,
            corner_radius=10,
            border_width=1,
            border_color=T.SURFACE_BORDER,
        )
        self.status_chip.grid(row=0, column=0, sticky="ew")
        self.status_chip.grid_columnconfigure(1, weight=1)

        # 第一行：状态点 + 标题 + 断开
        head = ctk.CTkFrame(self.status_chip, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 2))
        head.grid_columnconfigure(1, weight=1)

        self.status_dot = ctk.CTkLabel(
            head, text="●", text_color=T.IDLE, width=14, font=mono_font(9)
        )
        self.status_dot.grid(row=0, column=0, padx=(0, 4))

        self.status_label = ctk.CTkLabel(
            head,
            text="未连接",
            anchor="w",
            text_color=T.MUTED,
            font=ui_font(12, "bold"),
        )
        self.status_label.grid(row=0, column=1, sticky="ew")

        self.btn_disconnect = ctk.CTkButton(
            head,
            text="断开",
            width=44,
            height=26,
            corner_radius=6,
            fg_color=T.SURFACE_MUTED,
            hover_color=T.SURFACE_HOVER,
            border_width=1,
            border_color=T.SURFACE_BORDER,
            text_color=T.TEXT_DIM,
            font=ui_font(11),
            command=on_disconnect,
            state="disabled",
        )
        self.btn_disconnect.grid(row=0, column=2, padx=(4, 0))

        # 第二行：连接目标（user@host:port），可换行
        detail_wrap = T.SIDEBAR_WIDTH - 48
        self.status_detail = ctk.CTkLabel(
            self.status_chip,
            text="",
            anchor="w",
            justify="left",
            text_color=T.MUTED,
            font=mono_font(10),
            wraplength=max(detail_wrap, 120),
        )
        self.status_detail.grid(
            row=1, column=0, columnspan=2, sticky="ew", padx=(26, 10), pady=(0, 8)
        )
        self.status_detail.grid_remove()

        steps_wrap = ctk.CTkFrame(self, fg_color="transparent")
        steps_wrap.grid(row=2, column=0, sticky="ew", padx=10, pady=(14, 6))

        for i, (name, desc) in enumerate(STEPS):
            row = ctk.CTkFrame(
                steps_wrap,
                fg_color="transparent",
                corner_radius=10,
                cursor="hand2",
            )
            row.pack(fill="x", pady=3)
            row.bind("<Button-1>", lambda _e, idx=i: self._click(idx))
            self._rows.append(row)

            left = ctk.CTkFrame(row, fg_color="transparent", width=36)
            left.pack(side="left", padx=(6, 4), pady=8)
            left.bind("<Button-1>", lambda _e, idx=i: self._click(idx))

            dot = ctk.CTkLabel(
                left,
                text=f"{i + 1:02d}",
                width=T.STEPPER_DOT,
                height=T.STEPPER_DOT,
                corner_radius=T.STEPPER_DOT // 2,
                fg_color=T.SURFACE_MUTED,
                text_color=T.MUTED,
                font=mono_font(10),
            )
            dot.pack()
            dot.bind("<Button-1>", lambda _e, idx=i: self._click(idx))

            text_col = ctk.CTkFrame(row, fg_color="transparent")
            text_col.pack(side="left", fill="x", expand=True, pady=6)
            text_col.bind("<Button-1>", lambda _e, idx=i: self._click(idx))
            name_lbl = ctk.CTkLabel(
                text_col,
                text=name,
                anchor="w",
                text_color=T.MUTED,
                font=ui_font(12, "bold"),
            )
            name_lbl.pack(anchor="w")
            name_lbl.bind("<Button-1>", lambda _e, idx=i: self._click(idx))
            desc_lbl = ctk.CTkLabel(
                text_col,
                text=desc,
                anchor="w",
                text_color=T.MUTED,
                font=ui_font(10),
            )
            desc_lbl.pack(anchor="w")
            desc_lbl.bind("<Button-1>", lambda _e, idx=i: self._click(idx))

            self._dots.append(dot)
            self._name_labels.append(name_lbl)
            self._desc_labels.append(desc_lbl)
            self._row_style.append("")

        side_actions = ctk.CTkFrame(self, fg_color="transparent")
        side_actions.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 8))
        side_actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            side_actions,
            text="导入配置",
            height=32,
            corner_radius=8,
            fg_color=T.SURFACE_MUTED,
            hover_color=T.SURFACE_HOVER,
            border_width=1,
            border_color=T.SURFACE_BORDER,
            text_color=T.TEXT,
            font=ui_font(11),
            command=on_import,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(
            side_actions,
            text="导出配置",
            height=32,
            corner_radius=8,
            fg_color=T.SURFACE_MUTED,
            hover_color=T.SURFACE_HOVER,
            border_width=1,
            border_color=T.SURFACE_BORDER,
            text_color=T.TEXT,
            font=ui_font(11),
            command=on_export,
        ).grid(row=1, column=0, sticky="ew")

        legal = ctk.CTkFrame(self, fg_color="transparent")
        legal.grid(row=5, column=0, sticky="ew", padx=10, pady=(4, 12))
        wrap = max(T.SIDEBAR_WIDTH - 28, 120)
        ctk.CTkLabel(
            legal,
            text=f"版权所有：{COPYRIGHT_HOLDER}",
            anchor="center",
            justify="center",
            text_color=T.TEXT_DIM,
            font=ui_font(10),
            height=16,
            wraplength=wrap,
        ).pack(fill="x")
        ctk.CTkLabel(
            legal,
            text=f"程序开发：{COPYRIGHT_DEVELOPER}",
            anchor="center",
            justify="center",
            text_color=T.TEXT_DIM,
            font=ui_font(10),
            height=16,
            wraplength=wrap,
        ).pack(fill="x")
        ctk.CTkLabel(
            legal,
            text=f"HomeOS Deploy v{__version__}",
            anchor="center",
            justify="center",
            text_color=T.IDLE,
            font=mono_font(9),
            height=14,
        ).pack(fill="x", pady=(1, 0))

        # 右侧细线分隔
        ctk.CTkFrame(self, fg_color=T.HEADER_LINE, width=1).place(
            relx=1.0, rely=0, relheight=1.0, anchor="ne"
        )

    def _click(self, idx: int) -> None:
        if self._busy:
            return
        self._on_step(idx)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy

    def set_status(self, connected: bool, text: str) -> None:
        raw = (text or "").strip()
        title = raw or "未连接"
        detail = ""

        if connected and raw.startswith("已连接"):
            title = "已连接"
            detail = raw[len("已连接") :].strip()
        elif raw.startswith("连接中"):
            title = "连接中…"
        elif not connected:
            title = raw if raw in ("未连接", "连接中…", "连接中...") else (raw or "未连接")
            if title.startswith("已连接"):
                title = "未连接"

        color = T.SUCCESS if connected else (T.ACCENT if title.startswith("连接中") else T.IDLE)
        self.status_dot.configure(text_color=color)
        self.status_label.configure(
            text=title,
            text_color=T.ACCENT_ON_DARK if connected else T.MUTED,
        )

        if detail:
            self.status_detail.configure(text=detail, text_color=T.TEXT_DIM)
            self.status_detail.grid()
        else:
            self.status_detail.configure(text="")
            self.status_detail.grid_remove()

        self.btn_disconnect.configure(state="normal" if connected else "disabled")

    def set_milestones(self, milestones: Milestones) -> None:
        self._milestones = milestones
        self.refresh_styles()

    def set_current_step(self, idx: int) -> None:
        self._current = idx
        self.refresh_styles()

    def refresh_styles(self) -> None:
        for i, (dot, name_lbl, desc_lbl, row) in enumerate(
            zip(self._dots, self._name_labels, self._desc_labels, self._rows)
        ):
            done = False
            if i == 0:
                done = self._milestones.connected
            elif i == 1:
                done = self._milestones.logged_in
            elif i == 2:
                done = self._milestones.deployed
            else:
                done = self._milestones.deployed or self._milestones.connected

            if i == self._current:
                key = "current"
            elif done:
                key = "done"
            else:
                key = "idle"
            if self._row_style[i] == key:
                continue
            self._row_style[i] = key

            if key == "current":
                row.configure(fg_color=T.SURFACE)
                dot.configure(
                    fg_color=T.ACCENT,
                    text_color="#041018",
                    text=f"{i + 1:02d}",
                )
                name_lbl.configure(text_color=T.ACCENT)
                desc_lbl.configure(text_color=T.TEXT_DIM)
            elif key == "done":
                row.configure(fg_color="transparent")
                dot.configure(
                    fg_color=T.SIDEBAR_DONE,
                    text_color=T.SIDEBAR_DONE_TEXT,
                    text="完成",
                )
                name_lbl.configure(text_color=T.SIDEBAR_DONE_TEXT)
                desc_lbl.configure(text_color=T.MUTED)
            else:
                row.configure(fg_color="transparent")
                dot.configure(
                    fg_color=T.SURFACE_MUTED,
                    text_color=T.MUTED,
                    text=f"{i + 1:02d}",
                )
                name_lbl.configure(text_color=T.MUTED)
                desc_lbl.configure(text_color=T.MUTED)
