"""终端风格控制台：日志追加 / 复制 / 清空。"""

from __future__ import annotations

import customtkinter as ctk

from homeos_deploy import theme as T
from homeos_deploy.log_filter import should_show_log_line
from homeos_deploy.ui.components import mono_font, ui_font
from homeos_deploy.ui.constants import LOG_MAX_LINES

try:
    import win32clipboard
except ImportError:  # pragma: no cover
    win32clipboard = None  # type: ignore


class DeployConsole(ctk.CTkFrame):
    def __init__(self, master, **kwargs) -> None:
        super().__init__(
            master,
            fg_color=T.TERM_BG,
            corner_radius=T.RADIUS,
            border_width=1,
            border_color=T.TERM_BORDER,
            **kwargs,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._log_lines: list[str] = []
        # 清空后作废仍在排队的 after(0) 追加，避免「清了又冒出来」
        self._gen = 0
        self._flash_after: dict[str, object | None] = {"copy": None, "clear": None}

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="●", text_color="#FF5F57", font=mono_font(9), width=12
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            hdr, text="●", text_color="#FEBC2E", font=mono_font(9), width=12
        ).grid(row=0, column=0, sticky="w", padx=(14, 0))
        ctk.CTkLabel(
            hdr, text="●", text_color="#28C840", font=mono_font(9), width=12
        ).grid(row=0, column=0, sticky="w", padx=(28, 0))

        ctk.CTkLabel(
            hdr,
            text="  控制台",
            anchor="w",
            text_color=T.TERM_LABEL,
            font=ui_font(12),
        ).grid(row=0, column=1, sticky="w", padx=(36, 0))

        self._copy_btn = ctk.CTkButton(
            hdr,
            text="复制",
            width=52,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#0A1A14",
            text_color=T.MUTED,
            font=ui_font(11),
            command=self.copy_log,
        )
        self._copy_btn.grid(row=0, column=2, padx=2)
        self._clear_btn = ctk.CTkButton(
            hdr,
            text="清空",
            width=52,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color="#0A1A14",
            text_color=T.MUTED,
            font=ui_font(11),
            command=self.clear_log,
        )
        self._clear_btn.grid(row=0, column=3)

        self.log_box = ctk.CTkTextbox(
            self,
            corner_radius=8,
            fg_color=T.TERM_BG,
            text_color=T.TERM_FG,
            border_width=0,
            font=mono_font(12),
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))
        self.log_box.configure(state="disabled")

    @property
    def log_gen(self) -> int:
        return self._gen

    def append(self, line: str, *, gen: int | None = None) -> None:
        if gen is not None and gen != self._gen:
            return
        stripped = (line or "").strip()
        if not stripped:
            return
        if not should_show_log_line(stripped):
            return

        # 统一存展示文本，复制与界面一致
        display = stripped
        self._log_lines.append(display)
        if len(self._log_lines) > LOG_MAX_LINES:
            overflow = len(self._log_lines) - LOG_MAX_LINES
            self._log_lines = self._log_lines[overflow:]
            self._rewrite_box()
            return

        try:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", display + "\n")
            self.log_box.see("end")
        finally:
            self.log_box.configure(state="disabled")

    def clear_log(self) -> None:
        self._gen += 1
        self._log_lines.clear()
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
        finally:
            self.log_box.configure(state="disabled")
        self._flash_btn(self._clear_btn, "已清空", "清空", key="clear")

    def copy_log(self) -> None:
        text = self._current_text()
        if not text.strip():
            self._flash_btn(self._copy_btn, "无内容", "复制", key="copy")
            return
        if not self._set_clipboard(text):
            self._flash_btn(self._copy_btn, "失败", "复制", key="copy")
            return
        self._flash_btn(self._copy_btn, "已复制", "复制", key="copy")

    def focus_end(self) -> None:
        try:
            self.log_box.focus_set()
            self.log_box.see("end")
        except Exception:
            pass

    def _current_text(self) -> str:
        if self._log_lines:
            return "\n".join(self._log_lines)
        text = ""
        try:
            self.log_box.configure(state="normal")
            text = self.log_box.get("1.0", "end-1c")
        except Exception:
            text = ""
        finally:
            try:
                self.log_box.configure(state="disabled")
            except Exception:
                pass
        return text

    def _rewrite_box(self) -> None:
        try:
            self.log_box.configure(state="normal")
            self.log_box.delete("1.0", "end")
            if self._log_lines:
                self.log_box.insert("end", "\n".join(self._log_lines) + "\n")
            self.log_box.see("end")
        finally:
            self.log_box.configure(state="disabled")

    def _set_clipboard(self, text: str) -> bool:
        # Windows 上优先用 win32clipboard，Tk clipboard 常在焦点切换后丢失
        if win32clipboard is not None:
            try:
                # SetClipboardText 内部会 Open/CloseClipboard
                win32clipboard.SetClipboardText(text)
                return True
            except Exception:
                pass
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            # 再读一次，确认本进程已持有剪贴板内容
            _ = self.clipboard_get()
            return True
        except Exception:
            return False

    def _flash_btn(
        self, btn: ctk.CTkButton, temp: str, restore: str, *, key: str
    ) -> None:
        btn.configure(text=temp)
        prev = self._flash_after.get(key)
        if prev is not None:
            try:
                self.after_cancel(prev)
            except Exception:
                pass
        self._flash_after[key] = self.after(
            1500, lambda: btn.configure(text=restore)
        )


CollapsibleConsole = DeployConsole
