"""Acha partidas novas sem GSI, pelas APIs oficiais (só fora do jogo).

- FACEIT: histórico recente do seu nick -> cria a partida e tenta baixar a demo.
- Steam: share codes novos -> cria a partida e espera a demo (baixada no CS).
A cada 3 minutos, e nunca com o CS2 em primeiro plano.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from . import db, faceit, steam
from .demos import import_demo

log = logging.getLogger("coach.poller")
INTERVAL = 180
RECENT = 3 * 86400  # só partidas dos últimos 3 dias


class MatchPoller(threading.Thread):
    def __init__(self, busy: Callable[[], bool], on_demo: Callable[[int], None]):
        super().__init__(daemon=True, name="poller")
        self.busy = busy
        self.on_demo = on_demo

    def run(self) -> None:
        threading.Event().wait(10)
        while True:
            if not self.busy():
                for fn in (self.faceit_once, self.faceit_dates_once, self.steam_once):
                    try:
                        fn()
                    except Exception:
                        log.exception("Falha em %s", fn.__name__)
            threading.Event().wait(INTERVAL)

    def faceit_once(self) -> None:
        if not faceit.configured():
            return
        for it in faceit.recent_matches(limit=5):
            fid = it.get("match_id")
            fin = it.get("finished_at") or 0
            if not fid or time.time() - fin > RECENT:
                continue
            m = db.q1("SELECT id, demo_id FROM matches WHERE faceit_match_id=?", fid)
            if m and m["demo_id"]:
                continue
            if not m:
                with db.tx() as c:
                    mid = c.execute(
                        """INSERT INTO matches(started_at, ended_at, played_at, map, source, status, faceit_match_id, note)
                           VALUES(?,?,?,?, 'faceit', 'aguardando_demo', ?, ?)""",
                        (it.get("started_at") or fin, fin, fin, faceit.match_map(fid), fid,
                         f"Baixe a demo na sala da FACEIT ({faceit.room_url(fid)}); a pasta Downloads é monitorada."),
                    ).lastrowid
                log.info("Partida FACEIT nova: %s", fid)
            else:
                mid = m["id"]
            path = faceit.download_demo(fid)
            if path:
                got = import_demo(path, hint_match_id=mid)
                if got:
                    self.on_demo(got)

    def faceit_dates_once(self) -> None:
        """Data em que a partida foi jogada (a demo não guarda isso; o arquivo só tem a data do download)."""
        if not faceit.configured():
            return
        for r in db.q("""SELECT id, faceit_match_id FROM matches WHERE faceit_match_id IS NOT NULL
                         AND played_at IS NULL LIMIT 30"""):
            if self.busy():
                return
            fin = faceit.match_finished_at(r["faceit_match_id"])
            if fin:
                with db.tx() as c:
                    c.execute("UPDATE matches SET played_at=?, ended_at=? WHERE id=?", (fin, fin, r["id"]))

    def steam_once(self) -> None:
        for code in steam.fetch_new_codes():
            if db.q1("SELECT 1 FROM matches WHERE sharecode=?", code):
                continue
            with db.tx() as c:
                mid = c.execute(
                    """INSERT INTO matches(started_at, ended_at, source, status, sharecode, note)
                       VALUES(?,?, 'valve', 'aguardando_demo', ?, ?)""",
                    (db.now(), db.now(), code,
                     "No CS2: Assistir > Suas partidas > baixar a demo. Ela é importada sozinha."),
                ).lastrowid
                c.execute("UPDATE sharecodes SET match_id=? WHERE code=?", (mid, code))
            log.info("Partida Valve nova (share code %s)", code)
