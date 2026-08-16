"""Paramiko SSH 会话封装。"""

from __future__ import annotations

import socket
import threading
from typing import Callable, Optional

import paramiko

from homeos_deploy.log_filter import strip_ansi

OutputCallback = Callable[[str], None]


class SSHSession:
    """保持一条 SSH 连接，支持流式执行远程命令与取消。"""

    def __init__(self) -> None:
        self._client: Optional[paramiko.SSHClient] = None
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._cancel = threading.Event()
        self._active_channel: Optional[paramiko.Channel] = None

    @property
    def connected(self) -> bool:
        client = self._client
        if client is None:
            return False
        transport = client.get_transport()
        return transport is not None and transport.is_active()

    def connect(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        timeout: float = 20.0,
    ) -> None:
        self.close()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host,
                port=port,
                username=user,
                password=password,
                timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.AuthenticationException as exc:
            raise ConnectionError("远程认证失败：用户名或密码不正确。") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise ConnectionError(f"连接超时：无法在限定时间内连上 {host}:{port}。") from exc
        except (socket.error, OSError, paramiko.SSHException) as exc:
            raise ConnectionError(f"远程连接失败：{exc}") from exc

        self._client = client
        self._cancel.clear()

    def close(self) -> None:
        self.cancel()
        with self._lock:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
                self._client = None
            self._active_channel = None

    def cancel(self) -> None:
        self._cancel.set()
        with self._lock:
            ch = self._active_channel
            if ch is not None:
                try:
                    ch.close()
                except Exception:
                    pass

    def run(
        self,
        command: str,
        on_output: Optional[OutputCallback] = None,
        timeout: Optional[float] = None,
        get_pty: bool = False,
    ) -> tuple[int, str]:
        if not self.connected or self._client is None:
            raise ConnectionError("尚未建立远程连接。")

        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("已有远程命令在执行，请等待完成或取消后再试。")

        try:
            return self._run_locked(command, on_output, timeout, get_pty)
        finally:
            self._run_lock.release()

    def _run_locked(
        self,
        command: str,
        on_output: Optional[OutputCallback],
        timeout: Optional[float],
        get_pty: bool,
    ) -> tuple[int, str]:
        if not self.connected or self._client is None:
            raise ConnectionError("尚未建立远程连接。")

        self._cancel.clear()
        stdin, stdout, stderr = self._client.exec_command(
            command,
            get_pty=get_pty,
            timeout=timeout,
        )
        channel = stdout.channel
        with self._lock:
            self._active_channel = channel

        chunks: list[str] = []

        def _emit_piece(piece: str) -> None:
            if not piece:
                return
            piece = strip_ansi(piece).rstrip("\r\n")
            if not piece.strip():
                return
            # docker 进度常用 \r 刷新同一行
            chunks.append(piece + "\n")
            if on_output is not None:
                on_output(piece)

        def _read_stream(stream) -> None:
            buf = ""
            try:
                while not self._cancel.is_set():
                    data = stream.read(256)
                    if not data:
                        break
                    if isinstance(data, bytes):
                        text = data.decode("utf-8", errors="replace")
                    else:
                        text = data
                    buf += text
                    while True:
                        npos = buf.find("\n")
                        rpos = buf.find("\r")
                        if npos < 0 and rpos < 0:
                            break
                        if npos >= 0 and (rpos < 0 or npos <= rpos):
                            piece, buf = buf[:npos], buf[npos + 1 :]
                            if piece.endswith("\r"):
                                piece = piece[:-1]
                            _emit_piece(piece)
                        else:
                            piece, buf = buf[:rpos], buf[rpos + 1 :]
                            if piece:
                                _emit_piece(piece)
                if buf.strip():
                    _emit_piece(buf)
            except Exception:
                pass

        t_out = threading.Thread(target=_read_stream, args=(stdout,), daemon=True)
        t_err = threading.Thread(target=_read_stream, args=(stderr,), daemon=True)
        t_out.start()
        t_err.start()
        t_out.join()
        t_err.join()

        if self._cancel.is_set():
            try:
                channel.close()
            except Exception:
                pass
            with self._lock:
                self._active_channel = None
            raise InterruptedError("操作已取消。")

        exit_status = channel.recv_exit_status()
        with self._lock:
            self._active_channel = None
        try:
            stdin.close()
        except Exception:
            pass
        return exit_status, "".join(chunks)
