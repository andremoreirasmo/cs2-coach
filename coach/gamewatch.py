"""Sabe se você está jogando, sem tocar no jogo.

Só pergunta ao Windows qual janela está em primeiro plano e de qual programa ela é.
Nada é lido do processo do CS2.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32
_u32.GetForegroundWindow.restype = wintypes.HWND
_u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def foreground_exe() -> str:
    hwnd = _u32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wintypes.DWORD()
    _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        _k32.CloseHandle(h)


def cs2_in_foreground() -> bool:
    try:
        return foreground_exe() == "cs2.exe"
    except Exception:
        return False
