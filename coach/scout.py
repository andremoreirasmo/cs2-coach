"""Comparar você com outro jogador da FACEIT.

As demos das últimas partidas dele são baixadas pelo site (faceit_site), analisadas num banco
separado por jogador (data/scout/<nick>.db) e apagadas logo em seguida. O banco principal nunca
é tocado: as partidas dele não aparecem na sua lista nem entram nas suas estatísticas.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .config import DATA

DIR = DATA / "scout"
NICK = re.compile(r"[A-Za-z0-9_-]{2,32}")


def _key(nick: str) -> str:
    if not NICK.fullmatch(nick or ""):
        raise ValueError("Nick inválido.")
    return nick.lower()


def db_file(nick: str) -> Path:
    return DIR / f"{_key(nick)}.db"


def json_file(nick: str) -> Path:
    return DIR / f"{_key(nick)}.json"


def known_rooms(nick: str) -> set[str]:
    """Salas dele já analisadas (não baixa de novo)."""
    f = json_file(nick)
    if not f.exists():
        return set()
    return set(json.loads(f.read_text(encoding="utf-8")).get("salas", []))


# ---------------- roda em processo separado (a análise é pesada) ----------------
def analyze_job(dem: str, fid: str, steamid: str, nick: str, when: float | None) -> dict:
    """Importa e analisa uma demo dele no banco dele, apaga a demo e devolve os números atualizados."""
    from . import analysis, db, demos
    DIR.mkdir(parents=True, exist_ok=True)
    db.use(db_file(nick))
    analysis.migrate()
    db.kv_set("steamid", steamid)  # a análise trata o jogador comparado como "você" neste banco
    src = Path(dem)
    mid = None
    try:
        mid = demos.import_demo(src)
        if mid:
            with db.tx() as c:
                c.execute("UPDATE matches SET faceit_match_id=?, played_at=COALESCE(?, played_at) WHERE id=?",
                          (fid, when, mid))
            analysis.analyze(mid)
    finally:
        src.unlink(missing_ok=True)
        for r in db.q("SELECT path FROM demos WHERE path IS NOT NULL AND path!=''"):
            Path(r["path"]).unlink(missing_ok=True)  # não guarda a demo, só os números
        with db.tx() as c:
            c.execute("UPDATE demos SET path=''")
    return stats(nick, steamid, extra_room=fid if mid else None)


def stats(nick: str, steamid: str, extra_room: str | None = None) -> dict:
    """Números do jogador no banco dele (roda no processo que já está usando esse banco)."""
    from . import aim, db, overview
    ids = [r["id"] for r in db.q("SELECT id FROM matches WHERE analyzed_at IS NOT NULL ORDER BY COALESCE(played_at, ended_at) DESC")]
    rooms = {r["faceit_match_id"] for r in db.q("SELECT faceit_match_id FROM matches WHERE faceit_match_id IS NOT NULL")}
    if extra_room:
        rooms.add(extra_room)
    out = {"nick": nick, "steamid": steamid, "atualizado": time.time(), "salas": sorted(rooms),
           "total": overview._totals(steamid, ids), "mira": aim.mine(ids, steamid) if ids else None}
    json_file(nick).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


# ---------------- leitura (processo principal) ----------------
def listed() -> list[dict]:
    if not DIR.exists():
        return []
    out = []
    for f in sorted(DIR.glob("*.json"), key=lambda p: -p.stat().st_mtime):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        out.append({"nick": d["nick"], "partidas": (d.get("total") or {}).get("partidas", 0), "atualizado": d.get("atualizado")})
    return out


def load(nick: str) -> dict | None:
    f = json_file(nick)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def remove(nick: str) -> None:
    for f in (db_file(nick), json_file(nick), db_file(nick).with_name(db_file(nick).name + "-wal"),
              db_file(nick).with_name(db_file(nick).name + "-shm")):
        f.unlink(missing_ok=True)


def mine(n: int) -> dict:
    """Seus números nas suas últimas n partidas da FACEIT (mesma base de comparação)."""
    from . import aim, db, overview
    me = db.kv_get("steamid")
    if not me:
        return {}
    ids = overview._match_ids(me, "faceit", n)
    return {"total": overview._totals(me, ids), "mira": aim.mine(ids, me) if ids else None}
