"""Game State Integration: entende as mensagens que o CS2 envia e grava rounds no SQLite.

O GSI é um recurso oficial da Valve: o próprio jogo envia JSON por HTTP para
127.0.0.1. Nada é injetado, nenhuma memória é lida e nada é mostrado durante o jogo.

Detalhe importante: quando você morre, o bloco "player" passa a ser o jogador
que você está assistindo. Por isso só usamos "player" quando o steamid dele é o
mesmo do "provider" (você).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from . import db

log = logging.getLogger("coach.gsi")

TRACKED_MODES = {"competitive", "premier"}
RESUME_WINDOW = 3 * 3600  # retoma uma partida "ao_vivo" se o programa reiniciar no meio


@dataclass
class RoundAcc:
    my_team: str | None = None
    kills: int = 0
    headshots: int = 0
    damage: int = 0
    died: int = 0
    money_start: int | None = None
    equip_value: int | None = None
    health_end: int | None = None
    bomb: str | None = None
    saved_num: int | None = None   # número do round já gravado (fase "over")


@dataclass
class Tracker:
    on_match_end: Callable[[int], None] | None = None
    match_id: int | None = None
    map_name: str | None = None
    me: str | None = None
    round_phase: str | None = None
    acc: RoundAcc = field(default_factory=RoundAcc)
    last_team: str | None = None
    last_stats: dict = field(default_factory=dict)
    finished: bool = False
    last_map_seen: float = 0.0   # última mensagem do GSI com mapa (qualquer modo)

    # ---------- estado público ----------
    @property
    def in_match(self) -> bool:
        """True enquanto há partida rastreada rolando. Usado para NUNCA mostrar dicas durante o jogo."""
        return self.match_id is not None and not self.finished

    @property
    def busy(self) -> bool:
        """True se o CS está em QUALQUER mapa (DM, casual, aquecimento, partida...).
        Nada pesado roda nesse estado. O GSI manda heartbeat a cada 30 s, então 75 s sem
        mensagem com mapa = voltou ao menu ou fechou o jogo."""
        return self.in_match or time.time() - self.last_map_seen < 75

    # ---------- entrada ----------
    def handle(self, p: dict) -> list[str]:
        events: list[str] = []
        prov = p.get("provider") or {}
        if prov.get("steamid"):
            if self.me != prov["steamid"]:
                self.me = prov["steamid"]
                if not db.kv_get("steamid"):
                    db.kv_set("steamid", self.me)

        m = p.get("map")
        if not m:  # menu principal
            self.last_map_seen = 0.0
            return events
        self.last_map_seen = time.time()
        mode = (m.get("mode") or "").lower()
        if mode not in TRACKED_MODES:
            return events
        phase = m.get("phase")  # warmup | live | intermission | gameover
        name = m.get("name")
        ct = int((m.get("team_ct") or {}).get("score", 0))
        t = int((m.get("team_t") or {}).get("score", 0))

        if self._is_new_match(name, phase, ct, t):
            self._start_match(name, mode)
            events.append("match_started")
        if self.match_id is None or self.finished:
            return events

        player = p.get("player") or {}
        is_me = bool(self.me) and player.get("steamid") == self.me
        rnd = p.get("round") or {}
        rphase = rnd.get("phase")

        if phase in ("live", "gameover") and rphase:
            if rphase in ("freezetime", "live") and self.round_phase in (None, "over"):
                self.acc = RoundAcc()
            self._update_acc(player, is_me, rnd)
            if rphase == "over" or phase == "gameover":
                if self._save_round(m, rnd, ct, t):
                    events.append("round_ended")
            self.round_phase = rphase

        if is_me:
            self.last_team = player.get("team") or self.last_team
            self.last_stats = player.get("match_stats") or self.last_stats

        if phase == "gameover":
            self._finish(ct, t)
            events.append("match_ended")
        return events

    # ---------- partida ----------
    def _is_new_match(self, name, phase, ct, t) -> bool:
        if self.match_id is None:
            return phase in ("warmup", "live")
        if name != self.map_name:
            return True
        # nova partida no mesmo mapa: placar zerado depois de um gameover
        return self.finished and phase in ("warmup", "live") and ct + t == 0

    def _start_match(self, name: str, mode: str) -> None:
        # fecha partida anterior que não chegou ao fim
        if self.match_id is not None and not self.finished:
            with db.tx() as c:
                c.execute("UPDATE matches SET status='incompleta' WHERE id=?", (self.match_id,))
        resume = db.q1(
            "SELECT id FROM matches WHERE status='ao_vivo' AND map=? AND started_at>? ORDER BY id DESC LIMIT 1",
            name, db.now() - RESUME_WINDOW,
        )
        if resume:
            self.match_id = resume["id"]
            log.info("Retomando partida %s em %s", self.match_id, name)
        else:
            with db.tx() as c:
                cur = c.execute(
                    "INSERT INTO matches(started_at,map,mode,steamid,status) VALUES(?,?,?,?, 'ao_vivo')",
                    (db.now(), name, mode, self.me),
                )
                self.match_id = cur.lastrowid
            log.info("Partida %s iniciada em %s (%s)", self.match_id, name, mode)
        self.map_name = name
        self.finished = False
        self.round_phase = None
        self.acc = RoundAcc()
        self.last_stats = {}

    def _finish(self, ct: int, t: int) -> None:
        team = self.last_team or self.acc.my_team
        my, en = (ct, t) if team == "CT" else (t, ct)
        result = "vitoria" if my > en else "derrota" if my < en else "empate"
        s = self.last_stats
        with db.tx() as c:
            c.execute(
                """UPDATE matches SET ended_at=?, status='terminada', my_team_final=?, score_ct=?, score_t=?,
                   my_score=?, enemy_score=?, result=?, kills=?, assists=?, deaths=?, mvps=?, points=?
                   WHERE id=?""",
                (db.now(), team, ct, t, my, en, result, s.get("kills"), s.get("assists"), s.get("deaths"),
                 s.get("mvps"), s.get("score"), self.match_id),
            )
        self.finished = True
        log.info("Partida %s terminou: %s %s-%s", self.match_id, result, my, en)
        if self.on_match_end:
            self.on_match_end(self.match_id)

    # ---------- round ----------
    def _update_acc(self, player: dict, is_me: bool, rnd: dict) -> None:
        a = self.acc
        if rnd.get("bomb"):
            a.bomb = rnd["bomb"]
        if is_me:
            st = player.get("state") or {}
            a.my_team = player.get("team") or a.my_team
            a.kills = int(st.get("round_kills", a.kills) or 0)
            a.headshots = int(st.get("round_killhs", a.headshots) or 0)
            a.damage = int(st.get("round_totaldmg", a.damage) or 0)
            a.health_end = st.get("health", a.health_end)
            if a.money_start is None and "money" in st:
                a.money_start = st["money"]
            if rnd.get("phase") == "freezetime" or a.equip_value is None:
                a.equip_value = st.get("equip_value", a.equip_value)
            if st.get("health") == 0:
                a.died = 1
        elif player.get("steamid") and self.me and rnd.get("phase") == "live":
            a.died = 1  # assistindo outro jogador durante o round => você morreu

    def _save_round(self, m: dict, rnd: dict, ct: int, t: int) -> bool:
        wins = m.get("round_wins") or {}
        num = max(ct + t, max((int(k) for k in wins), default=0))
        if num <= 0:
            return False
        a = self.acc
        first = a.saved_num != num
        winner = rnd.get("win_team")
        win_type = wins.get(str(num))
        if not winner and win_type:
            winner = "CT" if win_type.startswith("ct_") else "T"
        with db.tx() as c:
            c.execute(
                """INSERT INTO rounds(match_id,round_num,my_team,winner,win_type,bomb,kills,headshots,damage,
                   died,money_start,equip_value,health_end,ended_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(match_id,round_num) DO UPDATE SET my_team=excluded.my_team,
                   winner=COALESCE(excluded.winner,winner), win_type=COALESCE(excluded.win_type,win_type),
                   bomb=excluded.bomb, kills=excluded.kills, headshots=excluded.headshots, damage=excluded.damage,
                   died=excluded.died, health_end=excluded.health_end""",
                (self.match_id, num, a.my_team, winner, win_type, a.bomb, a.kills, a.headshots, a.damage,
                 a.died, a.money_start, a.equip_value, a.health_end, db.now()),
            )
        a.saved_num = num
        return first
