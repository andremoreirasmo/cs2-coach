"""O que acontece depois do fim da partida (só depois do gameover, nunca durante).

1. Descobre a origem: FACEIT (histórico da Data API) ou Valve (novo share code).
2. Consegue a demo: FACEIT Downloads API, ou espera ela aparecer nas pastas monitoradas.
3. Quando a demo estiver pronta: chama on_demo_ready (análise entra na Etapa 2).
"""
from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from typing import Callable

from . import db, faceit, steam
from .demos import import_demo

log = logging.getLogger("coach.pipeline")

# tentativas (segundos após o fim da partida)
FACEIT_TRIES = [90, 300, 600, 1200, 1800]
STEAM_TRIES = [60, 180, 600, 1800]


class Pipeline(threading.Thread):
    def __init__(self, is_busy: Callable[[], bool], on_demo_ready: Callable[[int], None] | None = None):
        super().__init__(daemon=True, name="pipeline")
        self.is_busy = is_busy
        self.on_demo_ready = on_demo_ready
        self._heap: list = []
        self._seq = itertools.count()
        self._cv = threading.Condition()

    def schedule(self, delay: float, fn: Callable, *args) -> None:
        with self._cv:
            heapq.heappush(self._heap, (time.time() + delay, next(self._seq), fn, args))
            self._cv.notify()

    def match_ended(self, match_id: int) -> None:
        if faceit.configured():
            self.schedule(FACEIT_TRIES[0], self._check_faceit, match_id, 0)
        elif steam.configured():
            self.schedule(STEAM_TRIES[0], self._check_steam, match_id, 0)
        else:
            self._set(match_id, "aguardando_demo",
                      "Sem chaves configuradas: aguardando a demo aparecer nas pastas monitoradas.")

    # ---------- FACEIT ----------
    def _check_faceit(self, match_id: int, attempt: int) -> None:
        m = db.q1("SELECT * FROM matches WHERE id=?", match_id)
        if not m or m["demo_id"]:
            return
        fid = m["faceit_match_id"]
        if not fid:
            hit = faceit.recent_match_near(m["ended_at"])
            if hit:
                fid = hit["match_id"]
                with db.tx() as c:
                    c.execute("UPDATE matches SET source='faceit', faceit_match_id=? WHERE id=?", (fid, match_id))
                log.info("Partida %s é FACEIT (%s)", match_id, fid)
            elif attempt >= 1:  # não apareceu no histórico: provavelmente é Valve
                if steam.configured():
                    self.schedule(0, self._check_steam, match_id, 0)
                else:
                    self._set(match_id, "aguardando_demo", "Aguardando a demo nas pastas monitoradas.")
                return
        if fid:
            path = faceit.download_demo(fid)
            if path:
                mid = import_demo(path, hint_match_id=match_id)
                if mid and self.on_demo_ready:
                    self.on_demo_ready(mid)
                return
            self._set(match_id, "aguardando_demo",
                      f"Baixe a demo na sala da FACEIT ({faceit.room_url(fid)}); a pasta Downloads é monitorada.")
        if attempt + 1 < len(FACEIT_TRIES):
            self.schedule(FACEIT_TRIES[attempt + 1] - FACEIT_TRIES[attempt], self._check_faceit, match_id, attempt + 1)

    # ---------- Steam ----------
    def _check_steam(self, match_id: int, attempt: int) -> None:
        m = db.q1("SELECT * FROM matches WHERE id=?", match_id)
        if not m or m["sharecode"]:
            return
        steam.fetch_new_codes()
        code = steam.link_latest(match_id)
        if code:
            self._set(match_id, "aguardando_demo",
                      f"Share code {code}. No CS2: Assistir > Suas partidas > baixar a demo; ela é importada sozinha.")
            return
        if attempt + 1 < len(STEAM_TRIES):
            self.schedule(STEAM_TRIES[attempt + 1] - STEAM_TRIES[attempt], self._check_steam, match_id, attempt + 1)
        else:
            self._set(match_id, "aguardando_demo", "Share code não apareceu; aguardando demo nas pastas.")

    @staticmethod
    def _set(match_id: int, status: str, note: str) -> None:
        with db.tx() as c:
            c.execute("UPDATE matches SET status=?, note=? WHERE id=? AND demo_id IS NULL", (status, note, match_id))

    # ---------- loop ----------
    def run(self) -> None:
        while True:
            with self._cv:
                while not self._heap or self._heap[0][0] > time.time():
                    self._cv.wait(timeout=(self._heap[0][0] - time.time()) if self._heap else None)
                when, _, fn, args = heapq.heappop(self._heap)
            if self.is_busy():  # nova partida começou: adia, não usa rede/CPU durante o jogo
                self.schedule(120, fn, *args)
                continue
            try:
                fn(*args)
            except Exception:
                log.exception("Falha em %s%s", fn.__name__, args)
