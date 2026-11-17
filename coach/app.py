"""App com janela: python -m coach.app  (use o atalho "CS2 Coach").

- Abre uma janela própria (WebView2 do Windows) com a interface.
- Fechar a janela só esconde: o app continua na bandeja esperando a próxima partida.
- "Sair" no ícone da bandeja encerra de verdade.
- Abrir o atalho de novo só traz a janela de volta (instância única).
- --tray: inicia escondido (para iniciar com o Windows).
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from pathlib import Path

import httpx
import pystray
import uvicorn
import webview
from PIL import Image

from .config import DATA, ROOT, settings
from .server import create_app
from .services import Services, setup_logging

log = logging.getLogger("coach.app")
URL = f"http://127.0.0.1:{settings.gsi_port}"
ICO = ROOT / "assets" / "icon.ico"
PNG = ROOT / "assets" / "icon.png"


def already_running() -> bool:
    try:
        r = httpx.get(f"{URL}/api/status", timeout=1.5)
        if r.json().get("app") == "cs2-coach":
            httpx.post(f"{URL}/api/window/show", timeout=3)
            return True
    except Exception:
        pass
    return False


def set_window_icon(window) -> None:
    try:
        hwnd = window.native.Handle.ToInt64()
        u32 = ctypes.windll.user32
        u32.LoadImageW.restype = ctypes.c_void_p
        u32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        for kind, size in ((1, 32), (0, 16)):  # ICON_BIG, ICON_SMALL
            h = u32.LoadImageW(None, str(ICO), 1, size, size, 0x10)
            u32.SendMessageW(hwnd, 0x80, kind, h)  # WM_SETICON
    except Exception:
        log.debug("não consegui trocar o ícone da janela", exc_info=True)


def main() -> None:
    start_hidden = "--tray" in sys.argv
    if already_running():
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CS2Coach.App")
    setup_logging(console=False)

    state = {"quitting": False}
    window = None

    def show() -> None:
        if window:
            window.show()
            window.restore()

    def pick_files() -> list[str]:
        """Seletor de arquivos do Windows, dentro da janela do app."""
        if not window:
            return []
        res = window.create_file_dialog(
            webview.FileDialog.OPEN, directory=str(Path.home() / "Downloads"), allow_multiple=True,
            file_types=("Demos do CS2 (*.dem;*.gz;*.zst;*.bz2)", "Todos os arquivos (*.*)"))
        return list(res or [])

    services = Services()
    services.start()
    server = uvicorn.Server(uvicorn.Config(create_app(services.tracker, show_window=show, busy=services.in_game,
                                                      pick_files=pick_files, on_demo=services.analyzer.submit,
                     progress=services.analyzer.progress),
                                           host="127.0.0.1", port=settings.gsi_port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True, name="http").start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)

    # o número muda a cada build da interface, então a janela nunca usa uma versão velha do cache
    index = ROOT / "frontend" / "dist" / "index.html"
    build = int(index.stat().st_mtime) if index.exists() else 0
    window = webview.create_window("CS2 Coach", f"{URL}/?v={build}", width=1380, height=900, min_size=(1100, 700),
                                   background_color="#0a0c10", hidden=start_hidden, text_select=False)

    def on_closing():
        if state["quitting"]:
            return True
        threading.Thread(target=window.hide, daemon=True).start()
        return False  # cancela o fechamento: fica na bandeja

    def quit_app(icon=None, item=None):
        state["quitting"] = True
        tray.stop()
        server.should_exit = True
        try:
            window.destroy()
        finally:
            threading.Timer(1.5, lambda: os._exit(0)).start()

    window.events.closing += on_closing
    window.events.shown += lambda: set_window_icon(window)

    tray = pystray.Icon("cs2coach", Image.open(PNG), "CS2 Coach", menu=pystray.Menu(
        pystray.MenuItem("Abrir CS2 Coach", lambda *_: show(), default=True),
        pystray.MenuItem("Sair", quit_app),
    ))
    tray.run_detached()

    webview.start(gui="edgechromium", private_mode=False, storage_path=str(DATA / "webview"))
    os._exit(0)


if __name__ == "__main__":
    main()
