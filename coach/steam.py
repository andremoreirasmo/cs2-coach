"""Histórico de partidas da Valve (Premier/Competitivo) pela Web API oficial da Steam.

Usa só o endpoint público GetNextMatchSharingCode com o SEU código de autenticação.
Não faz login na Steam, não fala com o Game Coordinator e não mexe no cliente/jogo.

Limitação: a Valve não expõe a URL da demo por API pública. Para baixar a demo,
clique em "Baixar" no histórico de partidas do CS2 (Assistir > Suas partidas);
o monitor de pastas pega o arquivo automaticamente e liga pelo share code.
"""
from __future__ import annotations

import logging

import httpx

from . import db
from .config import settings
from .sharecode import decode

log = logging.getLogger("coach.steam")
URL = "https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1"


def configured() -> bool:
    return bool(settings.steam_key and settings.steam_auth_code and _steamid() and _last_code())


def _steamid() -> str | None:
    return settings.steam_id64 or db.kv_get("steamid")


def _last_code() -> str | None:
    return db.kv_get("steam_last_sharecode") or settings.steam_last_sharecode or None


def fetch_new_codes(max_codes: int = 20) -> list[str]:
    """Busca share codes novos desde o último conhecido."""
    if not configured():
        return []
    known = _last_code()
    new: list[str] = []
    with httpx.Client(timeout=15) as cli:
        for _ in range(max_codes):
            r = cli.get(URL, params={"key": settings.steam_key, "steamid": _steamid(),
                                     "steamidkey": settings.steam_auth_code, "knowncode": known})
            if r.status_code == 202:  # nenhum código novo
                break
            if r.status_code != 200:
                log.warning("Steam respondeu %s: verifique chave/código de autenticação", r.status_code)
                break
            code = (r.json().get("result") or {}).get("nextcode")
            if not code or code == "n/a":
                break
            d = decode(code)
            with db.tx() as c:
                c.execute("""INSERT OR IGNORE INTO sharecodes(code,match_id_valve,outcome_id,token,fetched_at)
                             VALUES(?,?,?,?,?)""",
                          (code, str(d["match_id"]), str(d["outcome_id"]), d["token"], db.now()))
            db.kv_set("steam_last_sharecode", code)
            new.append(code)
            known = code
    if new:
        log.info("%d share code(s) novo(s)", len(new))
    return new


def link_latest(match_id: int) -> str | None:
    """Liga o share code mais recente (ainda livre) à partida que acabou de terminar."""
    r = db.q1("SELECT code FROM sharecodes WHERE match_id IS NULL ORDER BY fetched_at DESC, rowid DESC LIMIT 1")
    if not r:
        return None
    with db.tx() as c:
        c.execute("UPDATE sharecodes SET match_id=? WHERE code=?", (match_id, r["code"]))
        c.execute("UPDATE matches SET sharecode=?, source='valve' WHERE id=?", (r["code"], match_id))
    return r["code"]


# ---------------- fotos e nomes de perfil ----------------
PROFILES_SQL = """CREATE TABLE IF NOT EXISTS steam_profiles (
    steamid TEXT PRIMARY KEY, name TEXT, avatar TEXT, profile_url TEXT, fetched_at REAL
)"""
SUMMARIES = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
PROFILE_TTL = 3 * 86400


def migrate_profiles() -> None:
    with db.tx() as c:
        c.execute(PROFILES_SQL)


def refresh_profiles() -> int:
    """Busca foto e nome de perfil dos jogadores das suas partidas (Web API oficial, de 100 em 100).
    Só precisa da chave Web API; perfis privados também têm foto e nome públicos."""
    if not settings.steam_key:
        return 0
    migrate_profiles()
    ids = [r["steamid"] for r in db.q(
        """SELECT DISTINCT p.steamid FROM demo_players p LEFT JOIN steam_profiles s ON s.steamid=p.steamid
           WHERE (s.steamid IS NULL OR s.fetched_at < ?) AND length(p.steamid)=17""", db.now() - PROFILE_TTL)]
    me = db.kv_get("steamid")
    if me and me not in ids and not db.q1("SELECT 1 FROM steam_profiles WHERE steamid=?", me):
        ids.append(me)
    n = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            r = httpx.get(SUMMARIES, params={"key": settings.steam_key, "steamids": ",".join(chunk)}, timeout=20)
            r.raise_for_status()
            players = r.json().get("response", {}).get("players", [])
        except Exception as e:  # sem expor a URL (ela leva a chave)
            log.warning("Não deu para buscar perfis da Steam: %s", type(e).__name__)
            return n
        with db.tx() as c:
            for p in players:
                avatar = p.get("avatarfull") or p.get("avatarmedium") or ""
                if not avatar.startswith("https://avatars.steamstatic.com/") and not avatar.startswith("https://avatars.akamai.steamstatic.com/"):
                    avatar = ""  # só aceita imagens do servidor oficial de avatares da Steam
                c.execute("""INSERT INTO steam_profiles(steamid, name, avatar, profile_url, fetched_at) VALUES(?,?,?,?,?)
                             ON CONFLICT(steamid) DO UPDATE SET name=excluded.name, avatar=excluded.avatar,
                             profile_url=excluded.profile_url, fetched_at=excluded.fetched_at""",
                          (p.get("steamid"), p.get("personaname"), avatar, p.get("profileurl"), db.now()))
                n += 1
    if n:
        log.info("Perfis da Steam atualizados: %d", n)
    return n


def avatars(steamids: list[str]) -> dict[str, dict]:
    migrate_profiles()
    if not steamids:
        return {}
    marks = ",".join("?" * len(steamids))
    return {r["steamid"]: {"avatar": r["avatar"], "perfil": r["profile_url"], "steam_name": r["name"]}
            for r in db.q(f"SELECT * FROM steam_profiles WHERE steamid IN ({marks})", *steamids)}
