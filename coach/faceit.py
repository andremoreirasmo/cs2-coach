"""FACEIT pela Data API oficial (open.faceit.com).

- Descobre se a partida que acabou foi na FACEIT (histórico do seu nickname).
- Baixa a demo pela Downloads API se você tiver o token (acesso precisa ser pedido à FACEIT).
- Sem o token: registra o link da sala; baixe a demo lá e o monitor de Downloads importa.
Nada aqui interage com o FACEIT AC ou com o cliente da FACEIT.
"""
from __future__ import annotations

import logging
from pathlib import Path

import httpx

from . import db
from .config import DATA, settings

log = logging.getLogger("coach.faceit")
API = "https://open.faceit.com/data/v4"
DL_API = "https://open.faceit.com/download/v2/demos/download"
INBOX = DATA / "inbox"
INBOX.mkdir(exist_ok=True)


def configured() -> bool:
    return bool(settings.faceit_key and settings.faceit_nickname)


def _cli() -> httpx.Client:
    return httpx.Client(timeout=20, headers={"Authorization": f"Bearer {settings.faceit_key}"})


def player_id() -> str | None:
    pid = db.kv_get("faceit_player_id")
    if pid:
        return pid
    with _cli() as c:
        r = c.get(f"{API}/players", params={"nickname": settings.faceit_nickname})
        if r.status_code != 200:
            log.warning("FACEIT: nickname não encontrado (%s)", r.status_code)
            return None
        pid = r.json()["player_id"]
    db.kv_set("faceit_player_id", pid)
    return pid


def recent_match_near(ended_at: float, tolerance: float = 20 * 60) -> dict | None:
    """Partida FACEIT terminada perto do horário em que o GSI viu o gameover."""
    pid = player_id()
    if not pid:
        return None
    with _cli() as c:
        r = c.get(f"{API}/players/{pid}/history", params={"game": "cs2", "limit": 5})
        r.raise_for_status()
        for it in r.json().get("items", []):
            fin = it.get("finished_at") or 0
            if fin and abs(fin - ended_at) <= tolerance:
                return it
    return None


def recent_matches(limit: int = 5) -> list[dict]:
    pid = player_id()
    if not pid:
        return []
    with _cli() as c:
        r = c.get(f"{API}/players/{pid}/history", params={"game": "cs2", "limit": limit})
        r.raise_for_status()
        return r.json().get("items", [])


def match_map(faceit_match_id: str) -> str | None:
    """Mapa escolhido no veto (ex.: de_inferno)."""
    try:
        with _cli() as c:
            r = c.get(f"{API}/matches/{faceit_match_id}")
            r.raise_for_status()
            pick = ((r.json().get("voting") or {}).get("map") or {}).get("pick") or []
            return pick[0] if pick else None
    except Exception:
        return None


def match_finished_at(faceit_match_id: str) -> float | None:
    """Quando a partida terminou (horário Unix), pela Data API oficial."""
    try:
        with _cli() as c:
            r = c.get(f"{API}/matches/{faceit_match_id}")
            r.raise_for_status()
            return float(r.json().get("finished_at") or 0) or None
    except Exception:
        return None


def room_url(match_id: str) -> str:
    return f"https://www.faceit.com/pt/cs2/room/{match_id}"


def download_demo(faceit_match_id: str) -> Path | None:
    """Tenta baixar a demo. Retorna o caminho ou None (ainda não disponível / sem acesso)."""
    with _cli() as c:
        r = c.get(f"{API}/matches/{faceit_match_id}")
        r.raise_for_status()
        urls = r.json().get("demo_url") or []
    if not urls:
        return None
    if not settings.faceit_downloads_token:
        return None
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {settings.faceit_downloads_token}"}) as c:
        r = c.post(DL_API, json={"resource_url": urls[0]})
        if r.status_code != 200:
            log.warning("Downloads API recusou (%s). Baixe manualmente pela sala.", r.status_code)
            return None
        signed = r.json()["payload"]["download_url"]
        name = urls[0].rsplit("/", 1)[-1].split("?")[0] or f"{faceit_match_id}.dem.gz"
        dst = INBOX / name
        with c.stream("GET", signed) as resp:
            resp.raise_for_status()
            with open(dst.with_suffix(".part"), "wb") as f:
                for chunk in resp.iter_bytes(1 << 20):
                    f.write(chunk)
        dst.with_suffix(".part").replace(dst)
    return dst


# ---------------- level e elo dos jogadores (só com a chave da Data API) ----------------
def migrate_levels() -> None:
    with db.tx() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS faceit_profiles (
            steamid TEXT PRIMARY KEY, nickname TEXT, level INTEGER, elo INTEGER, fetched_at REAL)""")


def refresh_levels(max_players: int = 60) -> int:
    """Level e elo atuais na FACEIT dos jogadores das suas partidas FACEIT."""
    if not settings.faceit_key:
        return 0
    migrate_levels()
    ids = [r["steamid"] for r in db.q(
        """SELECT DISTINCT p.steamid FROM demo_players p JOIN matches m ON m.id=p.match_id
           LEFT JOIN faceit_profiles f ON f.steamid=p.steamid
           WHERE m.source='faceit' AND (f.steamid IS NULL OR f.fetched_at < ?) LIMIT ?""",
        db.now() - 3 * 86400, max_players)]
    n = 0
    with _cli() as c:
        for sid in ids:
            try:
                r = c.get(f"{API}/players", params={"game": "cs2", "game_player_id": sid})
                if r.status_code == 404:
                    data = {}
                else:
                    r.raise_for_status()
                    data = r.json()
            except Exception as e:
                log.warning("FACEIT: não deu para buscar o level (%s)", type(e).__name__)
                break
            cs2 = (data.get("games") or {}).get("cs2") or {}
            with db.tx() as t:
                t.execute("""INSERT INTO faceit_profiles(steamid, nickname, level, elo, fetched_at) VALUES(?,?,?,?,?)
                             ON CONFLICT(steamid) DO UPDATE SET nickname=excluded.nickname, level=excluded.level,
                             elo=excluded.elo, fetched_at=excluded.fetched_at""",
                          (sid, data.get("nickname"), cs2.get("skill_level"), cs2.get("faceit_elo"), db.now()))
            n += 1
    return n


def levels(steamids: list[str]) -> dict[str, dict]:
    migrate_levels()
    if not steamids:
        return {}
    marks = ",".join("?" * len(steamids))
    return {r["steamid"]: {"faceit_level": r["level"], "faceit_elo": r["elo"]}
            for r in db.q(f"SELECT * FROM faceit_profiles WHERE steamid IN ({marks})", *steamids)}
