"""共享 UI 组件 —— Aether Dock 深色科技风。"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from homeos_deploy import theme as T

_FONT_CACHE: dict[tuple[str, int, str], ctk.CTkFont] = {}


def ui_font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    key = (T.FONT_UI, size, weight)
    font = _FONT_CACHE.get(key)
    if font is None:
        font = ctk.CTkFont(family=T.FONT_UI, size=size, weight=weight)
        _FONT_CACHE[key] = font
    return font


def mono_font(size: int = 12) -> ctk.CTkFont:
    key = (T.FONT_MONO, size, "normal")
    font = _FONT_CACHE.get(key)
    if font is None:
        try:
            font = ctk.CTkFont(family=T.FONT_MONO, size=size)
        except Exception:
            font = ctk.CTkFont(family="Consolas", size=size)
        _FONT_CACHE[key] = font
    return font


class WidgetFactory:
    def __init__(self) -> None:
        self.action_btns: list[ctk.CTkButton] = []

    def secondary(
        self, parent, text: str, command: Callable, width: int = 100
    ) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=34,
            corner_radius=T.RADIUS_SM,
            fg_color=T.SURFACE_MUTED,
            hover_color=T.SURFACE_HOVER,
            text_color=T.TEXT,
            border_width=1,
            border_color=T.SURFACE_BORDER,
            font=ui_font(12),
        )
        self.action_btns.append(btn)
        return btn

    def danger(
        self, parent, text: str, command: Callable, width: int = 100
    ) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            width=width,
            height=34,
            corner_radius=T.RADIUS_SM,
            fg_color=T.DANGER_SOFT,
            hover_color=T.DANGER_SOFT_HOVER,
            text_color=T.DANGER,
            border_width=1,
            border_color="#4A2030",
            font=ui_font(12),
        )
        self.action_btns.append(btn)
        return btn


def field_block(
    parent: ctk.CTkFrame,
    row: int,
    label: str,
    *,
    column: int = 0,
    padx: tuple[int, int] = (0, 0),
    show: Optional[str] = None,
    columnspan: int = 1,
) -> ctk.CTkEntry:
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    wrap.grid(
        row=row,
        column=column,
        columnspan=columnspan,
        sticky="ew",
        padx=padx,
        pady=(0, T.FIELD_GAP),
    )
    wrap.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(
        wrap,
        text=label,
        anchor="w",
        text_color=T.MUTED,
        font=ui_font(11),
    ).grid(row=0, column=0, sticky="w")
    entry = ctk.CTkEntry(
        wrap,
        height=T.ENTRY_H,
        corner_radius=T.RADIUS_SM,
        fg_color=T.BG_ELEVATED,
        border_color=T.SURFACE_BORDER,
        border_width=1,
        text_color=T.TEXT,
        font=ui_font(13),
        show=show if show is not None else "",
    )
    entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    return entry


def tip_bar(parent: ctk.CTkFrame, text: str) -> ctk.CTkFrame:
    bar = ctk.CTkFrame(
        parent,
        fg_color=T.ACCENT_SOFT,
        corner_radius=T.RADIUS_SM,
        border_width=1,
        border_color="#1A4A42",
    )
    inner = ctk.CTkFrame(bar, fg_color="transparent")
    inner.pack(fill="x", padx=12, pady=9)
    ctk.CTkLabel(
        inner,
        text="▸",
        text_color=T.ACCENT,
        font=mono_font(12),
        width=16,
    ).pack(side="left")
    ctk.CTkLabel(
        inner,
        text=text,
        anchor="w",
        justify="left",
        text_color=T.TEXT_DIM,
        font=ui_font(12),
        wraplength=720,
    ).pack(side="left", fill="x", expand=True)
    return bar


def hint_label(parent: ctk.CTkFrame, text: str) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        parent,
        text=text,
        anchor="w",
        justify="left",
        text_color=T.MUTED,
        font=ui_font(11),
        wraplength=520,
    )


def section_card(parent: ctk.CTkFrame, title: str) -> tuple[ctk.CTkFrame, ctk.CTkFrame]:
    card = ctk.CTkFrame(
        parent,
        fg_color=T.BG_ELEVATED,
        corner_radius=T.RADIUS_SM,
        border_width=1,
        border_color=T.SURFACE_BORDER,
    )
    head = ctk.CTkFrame(card, fg_color="transparent")
    head.pack(fill="x", padx=14, pady=(12, 2))
    ctk.CTkLabel(
        head,
        text="◆",
        text_color=T.ACCENT,
        font=mono_font(10),
        width=14,
    ).pack(side="left")
    ctk.CTkLabel(
        head,
        text=title,
        anchor="w",
        text_color=T.ACCENT_ON_DARK,
        font=ui_font(11, "bold"),
    ).pack(side="left", padx=(4, 0))
    body = ctk.CTkFrame(card, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=14, pady=(4, 14))
    return card, body


def option_menu(
    parent: ctk.CTkFrame,
    values: list[str] | tuple[str, ...],
    *,
    width: Optional[int] = None,
) -> ctk.CTkOptionMenu:
    kwargs = dict(
        values=list(values),
        height=T.ENTRY_H,
        corner_radius=T.RADIUS_SM,
        fg_color=T.BG_ELEVATED,
        button_color=T.SURFACE_MUTED,
        button_hover_color=T.SURFACE_HOVER,
        text_color=T.TEXT,
        dropdown_fg_color=T.SURFACE,
        dropdown_hover_color=T.SURFACE_HOVER,
        dropdown_text_color=T.TEXT,
        font=ui_font(13),
        anchor="w",
    )
    if width is not None:
        kwargs["width"] = width
    return ctk.CTkOptionMenu(parent, **kwargs)
