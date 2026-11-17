"""Painel Geral: suas estatísticas somadas, por fonte (FACEIT x Premier/Competitivo), mapa e lado,
mais uma análise geral do Claude sobre o conjunto (gerada só quando você pede)."""
from __future__ import annotations

import logging
from collections import Counter

from . import db, duels
from .callouts import br

log = logging.getLogger("coach.overview")
SOURCES = {"faceit": "FACEIT", "valve": "Premier/Competitivo"}
def _me() -> str | None:
    return db.kv_get("steamid")


def _match_ids(me: str, source: str | None, last: int | None) -> list[int]:
    sql = """SELECT m.id FROM matches m JOIN demo_players p ON p.match_id=m.id AND p.steamid=?
             WHERE m.analyzed_at IS NOT NULL""" + (" AND m.source=?" if source else "") + \
          " ORDER BY COALESCE(m.played_at, m.ended_at, m.started_at) DESC" + (" LIMIT ?" if last else "")
    args = [me] + ([source] if source else []) + ([last] if last else [])
    return [r["id"] for r in db.q(sql, *args)]


def analyzed_count() -> int:
    return db.q1("SELECT COUNT(*) n FROM matches WHERE analyzed_at IS NOT NULL")["n"]


def _in(ids: list[int]) -> str:
    return ",".join(str(int(i)) for i in ids) or "NULL"


def _totals(me: str, ids: list[int]) -> dict | None:
    if not ids:
        return None
    r = dict(db.q1(f"""SELECT COUNT(*) n, SUM(p.kills) k, SUM(p.deaths) d, SUM(p.assists) a, SUM(p.damage) dmg,
                       SUM(p.rounds) rounds, AVG(p.rating) rating, AVG(p.kast) kast,
                       SUM(p.kills * p.hs_pct) / NULLIF(SUM(p.kills), 0) hs,
                       SUM(p.first_kills) fk, SUM(p.first_deaths) fd, SUM(p.trade_kills) tk, SUM(p.traded_deaths) td,
                       SUM(p.util_damage) util, SUM(p.enemies_flashed) flashed, SUM(p.flash_assists) fa,
                       SUM(p.clutches_won) cw, SUM(p.clutches) cl, SUM(p.multikills) mk,
                       SUM(m.result='vitoria') wins
                       FROM demo_players p JOIN matches m ON m.id=p.match_id
                       WHERE p.steamid=? AND p.match_id IN ({_in(ids)})""", me))
    rounds = max(1, r["rounds"] or 0)
    return {
        "partidas": r["n"], "vitorias": r["wins"] or 0, "winrate": round(100 * (r["wins"] or 0) / r["n"]),
        "nota": round(r["rating"] or 0, 2), "adr": round((r["dmg"] or 0) / rounds, 1), "kast": round(r["kast"] or 0, 1),
        "hs": round(r["hs"] or 0, 1), "kd": round((r["k"] or 0) / max(1, r["d"] or 0), 2),
        "kpr": round((r["k"] or 0) / rounds, 2), "dpr": round((r["d"] or 0) / rounds, 2),
        "abertura": round(100 * (r["fk"] or 0) / max(1, (r["fk"] or 0) + (r["fd"] or 0))),
        "aberturas_tentadas": round(100 * ((r["fk"] or 0) + (r["fd"] or 0)) / rounds),
        "trocadas": round(100 * (r["td"] or 0) / max(1, r["d"] or 0)),
        "trades": round((r["tk"] or 0) / r["n"], 1), "util": round((r["util"] or 0) / rounds, 1),
        "cegou": round((r["flashed"] or 0) / r["n"], 1), "clutch": f"{r['cw'] or 0}/{r['cl'] or 0}",
        "multikills": r["mk"] or 0, "rounds": r["rounds"] or 0,
    }


def _by_map(me: str, ids: list[int]) -> list[dict]:
    out = []
    for r in db.q(f"""SELECT m.map, COUNT(*) n, SUM(m.result='vitoria') w, AVG(p.rating) r,
                      SUM(p.damage) * 1.0 / SUM(p.rounds) adr, AVG(p.kast) kast
                      FROM matches m JOIN demo_players p ON p.match_id=m.id AND p.steamid=?
                      WHERE m.id IN ({_in(ids)}) GROUP BY m.map ORDER BY n DESC""", me):
        out.append({"mapa": r["map"], "partidas": r["n"], "winrate": round(100 * (r["w"] or 0) / r["n"]),
                    "nota": round(r["r"] or 0, 2), "adr": round(r["adr"] or 0, 1), "kast": round(r["kast"] or 0, 1)})
    return out


def _by_side(me: str, ids: list[int]) -> dict:
    out = {}
    for r in db.q(f"""SELECT pr.side, COUNT(*) n, SUM(pr.kills) k, SUM(pr.deaths) d, SUM(pr.damage) dmg,
                      SUM(pr.kast) kast, SUM(dr.winner_side = pr.side) w
                      FROM demo_player_rounds pr JOIN demo_rounds dr
                        ON dr.match_id=pr.match_id AND dr.round_num=pr.round_num
                      WHERE pr.steamid=? AND pr.match_id IN ({_in(ids)}) GROUP BY pr.side""", me):
        if r["side"] not in ("CT", "T"):
            continue
        n = max(1, r["n"])
        out[r["side"]] = {"rounds": r["n"], "winrate": round(100 * (r["w"] or 0) / n), "adr": round((r["dmg"] or 0) / n, 1),
                          "kpr": round((r["k"] or 0) / n, 2), "dpr": round((r["d"] or 0) / n, 2),
                          "kast": round(100 * (r["kast"] or 0) / n)}
    return out


def _deaths(me: str, ids: list[int]) -> dict | None:
    rows = [dict(r) for r in db.q(f"""SELECT k.*, m.map FROM demo_kills k JOIN matches m ON m.id=k.match_id
                                      WHERE k.victim=? AND k.match_id IN ({_in(ids)})""", me)]
    if not rows:
        return None
    n = len(rows)
    pct = lambda f: round(100 * sum(1 for r in rows if f(r)) / n)  # noqa: E731
    places = Counter(f"{br(r['map'], r['vic_place'])} ({(r['map'] or '').replace('de_', '').title()})" for r in rows if r.get("vic_place"))
    weapons = Counter(r["weapon"] for r in rows if r["weapon"])
    return {
        "total": n, "abertura": pct(lambda r: r["first_kill"]), "nao_trocadas": pct(lambda r: not r["traded"]),
        "sozinho": pct(lambda r: (r["mates_near"] or 0) == 0 and (r["mates_alive"] or 0) > 0),
        "sem_granada": pct(lambda r: not r["util_before"]), "cego": pct(lambda r: (r["victim_blind"] or 0) > 0),
        "headshot": pct(lambda r: r["headshot"]),
        "lugares": [{"lugar": k, "n": v} for k, v in places.most_common(8)],
        "armas": [{"arma": k, "n": v} for k, v in weapons.most_common(5)],
    }


def stats(source: str | None = None, last: int | None = None) -> dict:
    me = _me()
    if not me:
        return {"me": None, "analisadas": analyzed_count()}
    ids = _match_ids(me, source, last)
    trend = [dict(r) for r in db.q(f"""SELECT m.id, m.map, m.source, m.result, COALESCE(m.played_at, m.ended_at) quando,
                                       p.rating nota, p.adr FROM matches m JOIN demo_players p ON p.match_id=m.id AND p.steamid=?
                                       WHERE m.id IN ({_in(ids)}) ORDER BY COALESCE(m.played_at, m.ended_at, m.started_at)""", me)]
    by_source = {}
    for s in SOURCES:
        sid = _match_ids(me, s, last)
        by_source[s] = {"total": _totals(me, sid), "lados": _by_side(me, sid), "mortes": _deaths(me, sid)}
    pending = db.q1("""SELECT COUNT(*) n FROM matches WHERE analyzed_at IS NULL AND demo_id IS NOT NULL
                       AND status NOT IN ('erro','incompleta')""")["n"]
    return {"me": me, "total": _totals(me, ids), "mapas": _by_map(me, ids), "lados": _by_side(me, ids),
            "mortes": _deaths(me, ids), "duelos": duels.summary(ids, me), "fontes": by_source, "tendencia": trend, "na_fila": pending}


# ---------------- aba Mapas: pontos no radar ----------------
def maps_list() -> list[dict]:
    me = _me()
    if not me:
        return []
    return [dict(r) for r in db.q("""SELECT m.map, COUNT(*) partidas, SUM(m.source='faceit') faceit, SUM(m.source='valve') valve
                                     FROM matches m JOIN demo_players p ON p.match_id=m.id AND p.steamid=?
                                     WHERE m.analyzed_at IS NOT NULL AND m.map IS NOT NULL
                                     GROUP BY m.map ORDER BY partidas DESC""", me)]


def map_points(map_name: str, side: str | None = None, source: str | None = None, last: int | None = None) -> dict:
    me = _me()
    if not me:
        return {"me": None}
    sql = """SELECT m.id FROM matches m JOIN demo_players p ON p.match_id=m.id AND p.steamid=?
             WHERE m.analyzed_at IS NOT NULL AND m.map=?""" + (" AND m.source=?" if source else "") + \
          " ORDER BY COALESCE(m.played_at, m.ended_at, m.started_at) DESC" + (" LIMIT ?" if last else "")
    ids = [r["id"] for r in db.q(sql, *([me, map_name] + ([source] if source else []) + ([last] if last else [])))]
    side_sql = lambda col: f" AND {col}=?" if side in ("CT", "T") else ""  # noqa: E731
    side_arg = [side] if side in ("CT", "T") else []
    names = {(r["match_id"], r["steamid"]): r["name"] for r in db.q(
        f"SELECT match_id, steamid, name FROM demo_players WHERE match_id IN ({_in(ids)})")}
    when = {r["id"]: r["quando"] for r in db.q(
        f"SELECT id, COALESCE(played_at, ended_at, started_at) quando FROM matches WHERE id IN ({_in(ids)})")}

    deaths = []
    for k in db.q(f"""SELECT * FROM demo_kills WHERE victim=? AND match_id IN ({_in(ids)}) AND vx IS NOT NULL"""
                  + side_sql("victim_side"), me, *side_arg):
        k = dict(k)
        k["attacker_name"] = names.get((k["match_id"], k["attacker"]), "")
        k["vic_place"], k["att_place"] = br(map_name, k["vic_place"]), br(map_name, k["att_place"])
        k["quando"] = when.get(k["match_id"])
        deaths.append(k)
    kills = []
    for k in db.q(f"""SELECT * FROM demo_kills WHERE attacker=? AND victim!=? AND match_id IN ({_in(ids)}) AND ax IS NOT NULL"""
                  + side_sql("attacker_side"), me, me, *side_arg):
        k = dict(k)
        k["victim_name"] = names.get((k["match_id"], k["victim"]), "")
        k["vic_place"], k["att_place"] = br(map_name, k["vic_place"]), br(map_name, k["att_place"])
        k["quando"] = when.get(k["match_id"])
        kills.append(k)
    nades = [dict(g) for g in db.q(
        f"""SELECT match_id, round_num, side, type, tx, ty, x, y, z, enemies_blinded, mates_blinded, blind_time,
                   damage, hits, throw_tick FROM demo_grenades
            WHERE thrower=? AND match_id IN ({_in(ids)}) AND x IS NOT NULL""" + side_sql("side"), me, *side_arg)]
    return {"me": me, "partidas": len(ids), "mortes": deaths, "abates": kills, "granadas": nades}
