"""SQLite: partidas, rounds (via GSI), demos e share codes."""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      REAL NOT NULL,
    ended_at        REAL,
    map             TEXT,
    mode            TEXT,             -- modo cru do GSI (competitive, scrimcomp2v2, ...)
    source          TEXT,             -- faceit | valve | desconhecido
    steamid         TEXT,
    my_team_final   TEXT,             -- CT | T no fim da partida
    score_ct        INTEGER,
    score_t         INTEGER,
    my_score        INTEGER,
    enemy_score     INTEGER,
    result          TEXT,             -- vitoria | derrota | empate
    kills           INTEGER, assists INTEGER, deaths INTEGER, mvps INTEGER, points INTEGER,
    status          TEXT NOT NULL,    -- ao_vivo | terminada | aguardando_demo | demo_pronta | analisada
    faceit_match_id TEXT,
    sharecode       TEXT,
    demo_id         INTEGER,
    note            TEXT
);
CREATE TABLE IF NOT EXISTS rounds (
    match_id     INTEGER NOT NULL REFERENCES matches(id),
    round_num    INTEGER NOT NULL,
    my_team      TEXT,
    winner       TEXT,                -- CT | T
    win_type     TEXT,                -- ct_win_elimination, t_win_bomb, ...
    bomb         TEXT,
    kills        INTEGER, headshots INTEGER, damage INTEGER,
    died         INTEGER,
    money_start  INTEGER, equip_value INTEGER, health_end INTEGER,
    ended_at     REAL,
    PRIMARY KEY (match_id, round_num)
);
CREATE TABLE IF NOT EXISTS demos (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    original     TEXT NOT NULL UNIQUE,  -- caminho original + tamanho + mtime (assinatura)
    path         TEXT NOT NULL,         -- cópia .dem em data/demos
    map          TEXT,
    server_name  TEXT,
    source       TEXT,
    sharecode_matchid TEXT,
    file_time    REAL,
    added_at     REAL NOT NULL,
    match_id     INTEGER,
    status       TEXT NOT NULL          -- nova | vinculada | analisada | erro
);
CREATE TABLE IF NOT EXISTS sharecodes (
    code        TEXT PRIMARY KEY,
    match_id_valve TEXT,
    outcome_id  TEXT,
    token       INTEGER,
    fetched_at  REAL NOT NULL,
    match_id    INTEGER
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""

_lock = threading.RLock()


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path, check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


_con: sqlite3.Connection | None = None


def con() -> sqlite3.Connection:
    global _con
    if _con is None:
        _con = connect()
    return _con


def use(path: Path) -> None:
    """Troca o banco (usado nos testes)."""
    global _con
    _con = connect(path)


@contextmanager
def tx():
    with _lock:
        c = con()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def q(sql: str, *args) -> list[sqlite3.Row]:
    with _lock:
        return con().execute(sql, args).fetchall()


def q1(sql: str, *args) -> sqlite3.Row | None:
    rows = q(sql, *args)
    return rows[0] if rows else None


def kv_get(k: str, default: str | None = None) -> str | None:
    r = q1("SELECT v FROM kv WHERE k=?", k)
    return r["v"] if r else default


def kv_set(k: str, v: str) -> None:
    with tx() as c:
        c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


def now() -> float:
    return time.time()
