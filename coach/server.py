"""Servidor HTTP local (FastAPI): recebe o GSI, serve a API e a interface."""
from __future__ import annotations

import gzip
import hmac
import json
import logging
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import aim, analysis, cs2launch, db, duels, faceit, moments, overview, radar, steam, utility
from .config import ROOT, gsi_token
from .demos_api import make_router as make_demos_router
from .gsi import Tracker
from .settings_api import router as settings_router
from .settings_api import same_origin

log = logging.getLogger("coach.server")
DIST = ROOT / "frontend" / "dist"


def _rows(sql: str, *args) -> list[dict]:
    return [dict(r) for r in db.q(sql, *args)]


def create_app(tracker: Tracker, show_window: Callable[[], None] | None = None,
               busy: Callable[[], bool] | None = None,
               pick_files: Callable[[], list[str]] | None = None,
               on_demo: Callable[[int], None] = lambda mid: None,
               progress: Callable[[], dict] | None = None) -> FastAPI:
    app = FastAPI(title="CS2 Coach", docs_url=None, redoc_url=None)
    token = gsi_token()
    analysis.migrate()
    app.include_router(settings_router)
    app.include_router(make_demos_router(pick_files, on_demo))

    @app.post("/gsi")
    async def gsi(request: Request):
        if request.client and request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403)
        payload = await request.json()
        sent = ((payload.get("auth") or {}).get("token")) or ""
        if not hmac.compare_digest(sent, token):
            raise HTTPException(401)
        try:
            tracker.handle(payload)
        except Exception:  # nunca derrubar o servidor por uma mensagem estranha
            log.exception("Erro processando GSI")
        return {"ok": True}

    @app.get("/api/status")
    def status():
        return {"app": "cs2-coach", "em_partida": tracker.in_match or bool(busy and busy()), "mapa": tracker.map_name,
                "me": db.kv_get("steamid"), "fila": progress() if progress else None, "build": _build()}

    @app.post("/api/window/show")
    def window_show():
        if show_window:
            show_window()
        return {"ok": True}

    @app.get("/api/matches")
    def matches():
        return _rows("""SELECT id, started_at, ended_at, map, source, status, note, result, my_score, enemy_score,
                        team_a, team_b, score_a, score_b, rounds_total, my_rating, analyzed_at, faceit_match_id, played_at,
                        (SELECT name FROM demo_players p WHERE p.match_id=matches.id AND p.team='A'
                         ORDER BY rating DESC LIMIT 1) AS mvp_a,
                        (SELECT name FROM demo_players p WHERE p.match_id=matches.id AND p.team='B'
                         ORDER BY rating DESC LIMIT 1) AS mvp_b
                        FROM matches WHERE status!='incompleta'
                        ORDER BY COALESCE(played_at, ended_at, started_at) DESC LIMIT 200""")

    @app.get("/api/matches/{mid}")
    def match(mid: int):
        m = db.q1("SELECT * FROM matches WHERE id=?", mid)
        if not m:
            raise HTTPException(404)
        players = _rows("SELECT * FROM demo_players WHERE match_id=? ORDER BY rating DESC", mid)
        av = steam.avatars([p["steamid"] for p in players])
        lv = faceit.levels([p["steamid"] for p in players]) if m["source"] == "faceit" else {}
        for p in players:
            p.update(av.get(p["steamid"], {}))
            p.update(lv.get(p["steamid"], {}))
        return {
            "match": dict(m),
            "players": players,
            "rounds": _rows("SELECT * FROM demo_rounds WHERE match_id=? ORDER BY round_num", mid),
            "kills": _rows("SELECT * FROM demo_kills WHERE match_id=? ORDER BY tick", mid),
            "gsi_rounds": _rows("SELECT * FROM rounds WHERE match_id=? ORDER BY round_num", mid),
            # por round, para recalcular a tabela num período (clique no placar do half)
            "player_rounds": _rows("""SELECT round_num, steamid, kills, deaths, assists, damage, kast
                                       FROM demo_player_rounds WHERE match_id=?""", mid),
            "util_rounds": _rows("""SELECT round_num, thrower steamid, SUM(damage) dmg FROM demo_grenades
                                     WHERE match_id=? AND type IN ('he','molotov') GROUP BY round_num, thrower""", mid),
        }

    @app.get("/api/matches/{mid}/rounds/{rn}")
    def round_detail(mid: int, rn: int):
        r = db.q1("SELECT * FROM demo_rounds WHERE match_id=? AND round_num=?", mid, rn)
        if not r:
            raise HTTPException(404)
        rep = db.q1("SELECT data FROM demo_replays WHERE match_id=? AND round_num=?", mid, rn)
        nades = _rows("SELECT * FROM demo_grenades WHERE match_id=? AND round_num=? ORDER BY throw_tick", mid, rn)
        for g in nades:
            g["path"] = json.loads(g["path"] or "[]")
            g["blinded"] = json.loads(g["blinded"] or "[]")
        return {
            "round": dict(r),
            "total": db.q1("SELECT COUNT(*) n FROM demo_rounds WHERE match_id=?", mid)["n"],
            "map": db.q1("SELECT map FROM matches WHERE id=?", mid)["map"],
            "kills": _rows("SELECT * FROM demo_kills WHERE match_id=? AND round_num=? ORDER BY tick", mid, rn),
            "grenades": nades,
            "bomb": _rows("SELECT * FROM demo_bomb WHERE match_id=? AND round_num=? ORDER BY tick", mid, rn),
            "clutches": _rows("SELECT * FROM demo_clutches WHERE match_id=? AND round_num=?", mid, rn),
            "economy": _rows("SELECT * FROM demo_player_rounds WHERE match_id=? AND round_num=?", mid, rn),
            "replay": json.loads(gzip.decompress(rep["data"])) if rep else None,
        }

    @app.get("/api/maps/{name}/overview")
    def map_overview(name: str):
        ov = radar.overview(name)
        if not ov:
            raise HTTPException(404)
        return ov

    @app.get("/api/radar/{file}")
    def radar_image(file: str):
        f = (radar.OUT / file).resolve()
        if f.parent != radar.OUT.resolve() or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f, headers={"Cache-Control": "max-age=86400"})

    @app.get("/api/mapshot/{name}")
    def map_shot(name: str):
        f = (radar.SHOTS / f"{name}.jpg").resolve()
        if f.parent != radar.SHOTS.resolve() or not f.is_file():
            raise HTTPException(404)
        return FileResponse(f, headers={"Cache-Control": "max-age=604800"})

    @app.get("/api/me")
    def me_get():
        sid = db.kv_get("steamid")
        return {"steamid": sid, **(steam.avatars([sid]).get(sid, {}) if sid else {})}

    @app.post("/api/me")
    async def me_set(request: Request):
        same_origin(request)
        sid = str((await request.json()).get("steamid", ""))
        if not sid.isdigit() or len(sid) != 17:
            raise HTTPException(400, "steamid inválido")
        analysis.set_me(sid)
        return {"ok": True}

    @app.get("/api/overview")
    def get_overview(fonte: str = "todas", ultimas: int = 0):
        src = fonte if fonte in overview.SOURCES else None
        return overview.stats(src, ultimas if ultimas > 0 else None)

    @app.get("/api/mapas")
    def maps_list():
        return overview.maps_list()

    @app.get("/api/mapas/{name}")
    def map_points(name: str, lado: str = "ambos", fonte: str = "todas", ultimas: int = 0):
        return overview.map_points(name, lado if lado in ("CT", "T") else None,
                                   fonte if fonte in overview.SOURCES else None, ultimas if ultimas > 0 else None)

    @app.get("/api/mira")
    def get_aim(fonte: str = "todas", ultimas: int = 0, partida: int = 0, geral: int = 0):
        me = db.kv_get("steamid")
        if not me:
            return {"partidas": 0, "sem_jogador": True}
        if partida:
            ids = [partida]
        else:
            ids = overview._match_ids(me, fonte if fonte in overview.SOURCES else None, ultimas if ultimas > 0 else None)
        st = aim.stats(ids, me)
        st["faltam"] = len(aim.missing())
        if geral and not partida:  # base para comparar: todas as suas partidas (mesma fonte)
            st["geral"] = aim.mine(overview._match_ids(me, fonte if fonte in overview.SOURCES else None, None), me)
        return st

    @app.get("/api/granadas/{name}")
    def get_nades(name: str, tipo: str = "todas", lado: str = "ambos", fonte: str = "todas", ultimas: int = 0):
        me = db.kv_get("steamid")
        if not me:
            return {"grupos": [], "lances": []}
        ids = [r["id"] for r in db.q(
            """SELECT m.id FROM matches m JOIN demo_players p ON p.match_id=m.id AND p.steamid=?
               WHERE m.analyzed_at IS NOT NULL AND m.map=?""" + (" AND m.source=?" if fonte in overview.SOURCES else "")
            + " ORDER BY COALESCE(m.played_at, m.ended_at, m.started_at) DESC" + (" LIMIT ?" if ultimas > 0 else ""),
            *([me, name] + ([fonte] if fonte in overview.SOURCES else []) + ([ultimas] if ultimas > 0 else [])))]
        out = utility.library(name, ids, me, tipo if tipo in utility.TIPOS else None, lado if lado in ("CT", "T") else None)
        out["partidas"] = len(ids)
        return out

    @app.get("/api/matches/{mid}/mortes")
    def match_deaths(mid: int):
        return duels.match(mid)

    @app.get("/api/destaques")
    def best_plays(fonte: str = "todas", ultimas: int = 0):
        me = db.kv_get("steamid")
        if not me:
            return {"itens": [], "sem_jogador": True}
        ids = overview._match_ids(me, fonte if fonte in overview.SOURCES else None, ultimas if ultimas > 0 else None)
        return moments.best(ids)

    @app.get("/api/matches/{mid}/destaques")
    def match_highlights(mid: int):
        return moments.highlights(mid)

    @app.get("/api/matches/{mid}/economia")
    def match_economy(mid: int):
        return moments.economy(mid)

    @app.post("/api/cs2/demo")
    async def open_in_cs2(request: Request):
        """Abre a demo no CS2 pela Steam (só quando você clica) e copia o comando do lance."""
        same_origin(request)
        body = await request.json()
        try:
            mid, tick = int(body.get("match_id")), int(body.get("tick") or 0)
            sid = str(body.get("steamid") or "")
        except (TypeError, ValueError):
            raise HTTPException(400)
        return cs2launch.open_demo(mid, tick, sid)

    @app.get("/api/evolution")
    def evolution():
        me = db.kv_get("steamid")
        if not me:
            return []
        rows = _rows("""SELECT m.id, m.map, m.ended_at, m.result, p.rating, p.adr, p.kast, p.hs_pct,
                               p.kills, p.deaths, p.rounds, p.first_kills, p.first_deaths, p.trade_kills, p.traded_deaths,
                               p.util_damage, p.clutches_won, p.clutches
                        FROM matches m JOIN demo_players p ON p.match_id=m.id AND p.steamid=?
                        ORDER BY COALESCE(m.played_at, m.ended_at, m.started_at)""", me)
        # mira por partida: 1ª bala (rifle/pistola, sem sniper) e counter-strafe (parou antes de atirar)
        shots = {r["match_id"]: r for r in db.q(f"""
            SELECT match_id,
                   SUM(CASE WHEN burst=1 AND weapon NOT IN ('awp','ssg08','scar20','g3sg1') THEN 1 ELSE 0 END) f_n,
                   SUM(CASE WHEN burst=1 AND weapon NOT IN ('awp','ssg08','scar20','g3sg1') THEN hit ELSE 0 END) f_hit,
                   SUM(CASE WHEN strafe IS NOT NULL AND strafe!='parado' THEN 1 ELSE 0 END) s_n,
                   SUM(CASE WHEN strafe IN ('ok_cs','ok_solto') THEN 1 ELSE 0 END) s_ok
            FROM demo_shots WHERE steamid=? GROUP BY match_id""", me)}
        for r in rows:
            s = shots.get(r["id"])
            r["primeira_bala"] = round(100 * s["f_hit"] / s["f_n"], 1) if s and s["f_n"] else None
            r["parou"] = round(100 * s["s_ok"] / s["s_n"], 1) if s and s["s_n"] >= 5 else None
        return rows

    # ---- interface (build do Vite)
    def _build() -> int | None:
        """Muda a cada 'npm run build': a janela aberta se recarrega sozinha quando vê um número novo."""
        f = DIST / "index.html"
        return int(f.stat().st_mtime) if f.exists() else None

    if (DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, v: str | None = None):
        if v:
            log.info("Janela carregou a interface (build %s)", v)
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        if (DIST / "index.html").exists():
            return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
        return {"erro": "interface não compilada: rode 'npm run build' em frontend/"}

    return app
