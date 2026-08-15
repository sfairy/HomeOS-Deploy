"""统一操作栏 —— 嵌入内容卡底部。"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from homeos_deploy import theme as T
from homeos_deploy.ui.components import mono_font, ui_font
from homeos_deploy.ui.constants import STEP_PRIMARY, STEPS


class ActionBar(ctk.CTkFrame):
    def __init__(
        self,
        master,
        *,
        on_prev: Callable[[], None],
        on_next: Callable[[], None],
        on_primary: Callable[[], None],
        on_cancel: Callable[[], None],
        embedded: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=T.BG_ELEVATED,
            corner_radius=0,
            height=T.ACTION_BAR_H,
            **kwargs,
        )
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkFrame(self, fg_color=T.SURFACE_BORDER, height=1).grid(
            row=0, column=0, sticky="ew"
        )

        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.grid(row=1, column=0, sticky="ew", padx=16, pady=8)
        inner.grid_columnconfigure(1, weight=1)

        self.btn_prev = ctk.CTkButton(
            inner,
            text="上一步",
            width=88,
            height=34,
            corner_radius=T.RADIUS_SM,
            fg_color="transparent",
            hover_color=T.SURFACE_HOVER,
            border_width=1,
            border_color=T.SURFACE_BORDER,
            text_color=T.TEXT_DIM,
            font=ui_font(12),
            command=on_prev,
        )
        self.btn_prev.grid(row=0, column=0, sticky="w")

        center = ctk.CTkFrame(inner, fg_color="transparent")
        center.grid(row=0, column=1)

        self.btn_primary = ctk.CTkButton(
            center,
            text=STEP_PRIMARY[0],
            width=148,
            height=36,
            corner_radius=T.RADIUS_SM,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color="#041018",
            font=ui_font(13, "bold"),
            command=on_primary,
        )
        self.btn_primary.pack(side="left", padx=(0, 8))

        self.btn_cancel = ctk.CTkButton(
            center,
            text="取消",
            width=72,
            height=36,
            corner_radius=T.RADIUS_SM,
            fg_color=T.DANGER_SOFT,
            hover_color=T.DANGER_SOFT_HOVER,
            border_width=1,
            border_color="#4A2030",
            text_color=T.DANGER,
            font=ui_font(12),
            command=on_cancel,
            state="disabled",
        )
        self.btn_cancel.pack(side="left")
        self.btn_cancel.pack_forget()

        self.btn_next = ctk.CTkButton(
            inner,
            text="下一步",
            width=88,
            height=34,
            corner_radius=T.RADIUS_SM,
            fg_color=T.SURFACE_MUTED,
            hover_color=T.SURFACE_HOVER,
            border_width=1,
            border_color=T.ACCENT,
            text_color=T.ACCENT,
            font=ui_font(12, "bold"),
            command=on_next,
        )
        self.btn_next.grid(row=0, column=2, sticky="e")

        self._step = 0
        self._busy = False

    def set_step(self, idx: int) -> None:
        self._step = idx
        self.btn_primary.configure(text=STEP_PRIMARY[idx])
        self.btn_prev.configure(state="disabled" if idx <= 0 or self._busy else "normal")
        last = idx >= len(STEPS) - 1
        self.btn_next.configure(state="disabled" if last or self._busy else "normal")

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.btn_prev.configure(state="disabled")
            self.btn_next.configure(state="disabled")
            self.btn_primary.configure(state="disabled")
            self.btn_cancel.pack(side="left")
            self.btn_cancel.configure(state="normal")
        else:
            self.btn_cancel.pack_forget()
            self.btn_cancel.configure(state="disabled")
            self.btn_primary.configure(state="normal")
            self.set_step(self._step)
