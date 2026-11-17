"""Comandos para ver um lance no CS2.

Seguro: não abre nem mexe no jogo. Só monta "playdemo" e "demo_gototick" e copia o primeiro
para a área de transferência. Você cola no console do CS2 (tecla ').
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from pathlib import Path

from . import db


def copy(text: str) -> bool:
    """Copia texto para a área de transferência do Windows."""
    u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
    k32.GlobalAlloc.restype = wintypes.HGLOBAL
    k32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    u32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u32.SetClipboardData.restype = wintypes.HANDLE
    data = text.encode("utf-16-le") + b"\0\0"
    if not u32.OpenClipboard(None):
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        return bool(u32.SetClipboardData(13, h))  # CF_UNICODETEXT
    finally:
        u32.CloseClipboard()


STEAM64_BASE = 76561197960265728


def open_demo(match_id: int, tick: int, steamid: str = "") -> dict:
    """Só monta os comandos do lance. Não abre o jogo: você cola no console do CS2.

    O segundo comando pula para o lance e já põe a câmera no jogador (você, ou quem fez o lance).
    """
    r = db.q1("SELECT d.path, m.my_steamid FROM matches m JOIN demos d ON d.id=m.demo_id WHERE m.id=?", match_id)
    if not r or not Path(r["path"]).exists():
        return {"ok": False, "erro": "O arquivo da demo desta partida não está mais no PC."}
    play = f'playdemo "{Path(r["path"])}"'
    goto = f"demo_gototick {max(0, int(tick))}"
    sid = steamid if steamid.isdigit() else (r["my_steamid"] or "")
    if sid.isdigit() and int(sid) > STEAM64_BASE:
        goto += f"; spec_player_by_accountid {int(sid) - STEAM64_BASE}"
    copy(play)
    return {"ok": True, "play": play, "goto": goto}
