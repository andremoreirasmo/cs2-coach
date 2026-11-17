"""Etapa 2: análise completa da demo com demoparser2.

Por jogador: K/D/A, dano, ADR, HS%, KAST, primeiros abates, trades, dano de granada, clutches.
Por round: vencedor, motivo, economia/tipo de compra, bomba, granadas (trajetória, onde caiu,
quem cegou, dano) e replay (posições dos 10 jogadores 4x por segundo).
Por morte: quem matou e de onde, aliados vivos/perto, se foi trocada, se o morto usou granada
antes e se estava cego.
"""
from __future__ import annotations

import bisect
import gzip
import json
import logging
import math
from collections import defaultdict
from pathlib import Path

import pandas as pd
from demoparser2 import DemoParser

from . import aim, db

log = logging.getLogger("coach.analysis")

TICKRATE = 64
SAMPLE = 16                         # 64 ticks/s ÷ 16 = 4 amostras por segundo
TRADE_TICKS = 5 * TICKRATE          # morte vingada em até 5 s conta como trade
NEAR = 800                          # aliado a menos de 800 unidades (~20 m) "podia trocar"
UTIL_WEAPONS = {"hegrenade", "inferno", "molotov", "incgrenade"}
FLASH_MIN = 1.1                     # cegueira (s) que conta como "cegou"
NADE = {"CSmokeGrenadeProjectile": "smoke", "CFlashbangProjectile": "flash", "CHEGrenadeProjectile": "he",
        "CMolotovProjectile": "molotov", "CDecoyProjectile": "decoy"}
DETONATE = {"smoke": "smokegrenade_detonate", "flash": "flashbang_detonate", "he": "hegrenade_detonate",
            "molotov": "inferno_startburn", "decoy": "decoy_started"}
EFFECT_SECS = {"smoke": 18, "molotov": 7, "flash": 0.5, "he": 0.5, "decoy": 15}
SIDE = {2: "T", 3: "CT"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_players (
    match_id INTEGER, steamid TEXT, name TEXT, team TEXT, start_side TEXT,
    kills INTEGER, deaths INTEGER, assists INTEGER, damage INTEGER, adr REAL, hs_pct REAL, kast REAL,
    first_kills INTEGER, first_deaths INTEGER, trade_kills INTEGER, traded_deaths INTEGER,
    util_damage INTEGER, rounds INTEGER, rating REAL,
    flashes INTEGER, enemies_flashed INTEGER, flash_assists INTEGER, clutches_won INTEGER, clutches INTEGER,
    multikills INTEGER,
    PRIMARY KEY (match_id, steamid)
);
CREATE TABLE IF NOT EXISTS demo_rounds (
    match_id INTEGER, round_num INTEGER, winner_side TEXT, reason TEXT, winner_team TEXT,
    team_a_side TEXT, score_a INTEGER, score_b INTEGER, start_tick INTEGER, end_tick INTEGER,
    equip_a INTEGER, equip_b INTEGER, buy_a TEXT, buy_b TEXT,
    PRIMARY KEY (match_id, round_num)
);
CREATE TABLE IF NOT EXISTS demo_player_rounds (
    match_id INTEGER, round_num INTEGER, steamid TEXT, side TEXT, equip INTEGER, money INTEGER,
    kills INTEGER, deaths INTEGER, assists INTEGER, damage INTEGER, kast INTEGER,
    PRIMARY KEY (match_id, round_num, steamid)
);
CREATE TABLE IF NOT EXISTS demo_kills (
    match_id INTEGER, round_num INTEGER, tick INTEGER, round_time REAL,
    attacker TEXT, victim TEXT, assister TEXT, weapon TEXT, headshot INTEGER,
    attacker_side TEXT, victim_side TEXT, ax REAL, ay REAL, vx REAL, vy REAL,
    first_kill INTEGER, traded INTEGER, is_trade INTEGER,
    az REAL, vz REAL, att_dist REAL, mates_alive INTEGER, enemies_alive INTEGER, mate_dist REAL,
    mates_near INTEGER, util_before INTEGER, victim_blind REAL, dmg_sources INTEGER, flash_assist INTEGER,
    thru_smoke INTEGER, wallbang INTEGER, attacker_blind INTEGER, att_place TEXT, vic_place TEXT,
    vic_weapon TEXT, vic_nades INTEGER, vic_speed INTEGER, att_speed INTEGER, vic_angle INTEGER
);
CREATE TABLE IF NOT EXISTS demo_grenades (
    match_id INTEGER, round_num INTEGER, thrower TEXT, side TEXT, type TEXT,
    throw_tick INTEGER, det_tick INTEGER, end_tick INTEGER, tx REAL, ty REAL, x REAL, y REAL, z REAL,
    enemies_blinded INTEGER, mates_blinded INTEGER, blind_time REAL, damage INTEGER, hits INTEGER,
    blinded TEXT, path TEXT
);
CREATE TABLE IF NOT EXISTS demo_bomb (
    match_id INTEGER, round_num INTEGER, kind TEXT, tick INTEGER, steamid TEXT, site TEXT, x REAL, y REAL
);
CREATE TABLE IF NOT EXISTS demo_clutches (
    match_id INTEGER, round_num INTEGER, steamid TEXT, side TEXT, vs INTEGER, won INTEGER, kills INTEGER, tick INTEGER
);
CREATE TABLE IF NOT EXISTS demo_replays (
    match_id INTEGER, round_num INTEGER, data BLOB, PRIMARY KEY (match_id, round_num)
);
"""

MATCH_COLS = {"team_a": "TEXT", "team_b": "TEXT", "score_a": "INTEGER", "score_b": "INTEGER",
              "rounds_total": "INTEGER", "analyzed_at": "REAL", "my_steamid": "TEXT", "my_rating": "REAL",
              "analysis_version": "INTEGER", "played_at": "REAL"}
VERSION = 6  # 4: arma na mão e granadas guardadas de quem morreu; 5: velocidade e mira no duelo; 6: counter-strafe
TABLES = ["demo_players", "demo_rounds", "demo_player_rounds", "demo_kills", "demo_grenades", "demo_bomb",
          "demo_clutches", "demo_replays"]


def migrate() -> None:
    with db.tx() as c:
        # tabelas da versão 1 não têm as colunas novas: recria (dados são regerados da demo)
        cols = {r[1] for r in c.execute("PRAGMA table_info(demo_kills)")}
        if cols and "att_dist" not in cols:
            for t in ("demo_players", "demo_rounds", "demo_kills"):
                c.execute(f"DROP TABLE IF EXISTS {t}")
        c.executescript(SCHEMA)
        c.executescript(aim.SCHEMA)
        pcols = {r[1] for r in c.execute("PRAGMA table_info(demo_players)")}
        for col in ("rank", "rank_wins"):
            if col not in pcols:
                c.execute(f"ALTER TABLE demo_players ADD COLUMN {col} INTEGER")
        kcols = {r[1] for r in c.execute("PRAGMA table_info(demo_kills)")}
        for col, typ in (("att_place", "TEXT"), ("vic_place", "TEXT"), ("vic_weapon", "TEXT"), ("vic_nades", "INTEGER"),
                         ("vic_speed", "INTEGER"), ("att_speed", "INTEGER"), ("vic_angle", "INTEGER")):
            if col not in kcols:
                c.execute(f"ALTER TABLE demo_kills ADD COLUMN {col} {typ}")
        have = {r[1] for r in c.execute("PRAGMA table_info(matches)")}
        for col, typ in MATCH_COLS.items():
            if col not in have:
                c.execute(f"ALTER TABLE matches ADD COLUMN {col} {typ}")


def _ev(p, name: str, **kw) -> pd.DataFrame:
    """Lê um evento da demo. Se ele não aconteceu na partida, a biblioteca devolve uma lista vazia:
    aqui vira uma tabela vazia, para o resto do código não quebrar."""
    d = p.parse_event(name, **kw)
    if isinstance(d, pd.DataFrame):
        return d
    return pd.DataFrame(columns=["tick"])


def _ranks(p, tick: int) -> dict[str, tuple]:
    """Rank de cada jogador gravado na demo da Valve: Premier (ex.: 15550) ou nível do Competitivo (1-18),
    mais o número de vitórias. Na demo da FACEIT vem zerado."""
    try:
        df = p.parse_ticks(["rank", "comp_wins"], ticks=[int(tick)])
    except Exception:
        return {}
    out = {}
    for r in df.itertuples():
        rk = int(r.rank) if r.rank == r.rank and r.rank else 0
        out[str(r.steamid)] = (rk, int(r.comp_wins) if r.comp_wins == r.comp_wins else None)
    return out


def fill_ranks(match_id: int) -> None:
    """Preenche o rank das partidas analisadas antes desse campo existir (abre só um tick da demo)."""
    from demoparser2 import DemoParser
    r = db.q1("""SELECT d.path FROM matches m JOIN demos d ON d.id=m.demo_id WHERE m.id=?""", match_id)
    if not r or not Path(r["path"]).exists():
        return
    p = DemoParser(r["path"])
    ends = _ev(p, "round_end")
    if not len(ends):
        return
    ranks = _ranks(p, int(ends["tick"].max()))
    with db.tx() as c:
        for sid, (rk, wins) in ranks.items():
            c.execute("UPDATE demo_players SET rank=?, rank_wins=? WHERE match_id=? AND steamid=?",
                      (rk if rk else 0, wins, match_id, sid))
        # quem não apareceu no tick final fica com 0 (para não tentar de novo)
        c.execute("UPDATE demo_players SET rank=0 WHERE match_id=? AND rank IS NULL", (match_id,))


def _place(x) -> str | None:
    return str(x) if isinstance(x, str) and x else None


def _sid(x) -> str:
    return str(x) if x is not None and str(x) not in ("", "nan", "None") else ""


def _num(v, nd=0):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), nd) if nd else int(round(float(v)))


def _dist(a, b) -> float:
    return math.dist(a, b)


def buy_type(avg_equip: float, rn: int) -> str:
    if rn in (1, 13):
        return "pistol"
    if avg_equip < 1500:
        return "eco"
    if avg_equip < 3600:
        return "forçado"
    return "completo"


def analyze(match_id: int) -> None:
    migrate()
    m = db.q1("SELECT m.*, d.path FROM matches m JOIN demos d ON d.id=m.demo_id WHERE m.id=?", match_id)
    if not m:
        raise ValueError(f"partida {match_id} sem demo")
    path = Path(m["path"])
    log.info("Analisando partida %s (%s)", match_id, path.name)
    p = DemoParser(str(path))

    # ================= estrutura da partida =================
    bnm = _ev(p, "begin_new_match")
    start_tick = int(bnm["tick"].max()) if len(bnm) else 0
    ends = _ev(p, "round_end")
    ends = ends[(ends["tick"] > start_tick) & ends["winner"].notna()].reset_index(drop=True)
    n_rounds = len(ends)
    end_ticks = [int(t) for t in ends["tick"]]
    ranks = _ranks(p, end_ticks[-1]) if end_ticks else {}
    freeze = sorted(int(t) for t in _ev(p, "round_freeze_end")["tick"] if t > start_tick)[:n_rounds]
    while len(freeze) < n_rounds:  # demo cortada
        freeze.append(end_ticks[len(freeze)] - 1)
    try:
        bt = sorted(int(t) for t in _ev(p, "buytime_ended")["tick"] if t > start_tick)
    except Exception:
        bt = []
    buy_ticks = []
    for i in range(n_rounds):
        nxt = [t for t in bt if freeze[i] <= t < end_ticks[i]]
        buy_ticks.append(nxt[0] if nxt else min(freeze[i] + 20 * TICKRATE, end_ticks[i] - 1))

    def round_of(tick: int) -> int:
        """Round de um tick: do fim do congelamento até o próximo congelamento."""
        i = bisect.bisect_right(freeze, tick)
        return i if 1 <= i <= n_rounds else 0

    # ---- lado/time/economia de cada jogador em cada round
    tk = p.parse_ticks(["team_num", "team_clan_name", "current_equip_value", "balance"],
                       ticks=sorted(set(freeze + buy_ticks)))
    tk = tk[tk["steamid"].astype(str).str.len() == 17]
    fz_round = {t: i + 1 for i, t in enumerate(freeze)}
    bt_round = {t: i + 1 for i, t in enumerate(buy_ticks)}
    side: dict[tuple[int, str], str] = {}
    names: dict[str, str] = {}
    equip: dict[tuple[int, str], int] = defaultdict(int)
    money: dict[tuple[int, str], int] = {}
    clan: dict[tuple[int, str], str] = {}
    for r in tk.itertuples():
        sid, t = str(r.steamid), int(r.tick)
        s = SIDE.get(int(r.team_num)) if pd.notna(r.team_num) else None
        if not s:
            continue
        for rn in (fz_round.get(t), bt_round.get(t)):
            if not rn:
                continue
            if t in fz_round and fz_round[t] == rn:
                side[(rn, sid)] = s
                names[sid] = r.name
                if isinstance(r.team_clan_name, str) and r.team_clan_name:
                    clan[(rn, s)] = r.team_clan_name
            equip[(rn, sid)] = max(equip[(rn, sid)], int(r.current_equip_value or 0))
            if t in bt_round and bt_round[t] == rn:
                money[(rn, sid)] = int(r.balance or 0)

    team_a = {sid for (rn, sid), s in side.items() if rn == 1 and s == "CT"}
    team_b = {sid for (rn, sid), s in side.items() if rn == 1 and s == "T"}
    for (rn, sid), s in sorted(side.items()):  # quem entrou depois do round 1
        if sid not in team_a and sid not in team_b:
            swapped = (rn > 12) != (rn > 24 and ((rn - 25) // 3) % 2 == 1)
            (team_a if (s == "CT") != swapped else team_b).add(sid)
    name_a = clan.get((1, "CT"), "Time A")
    name_b = clan.get((1, "T"), "Time B")

    def a_side(rn: int) -> str:
        for sid in team_a:
            if (rn, sid) in side:
                return side[(rn, sid)]
        return "CT"

    def players_in(rn: int, s: str | None = None) -> set[str]:
        return {sid for (r, sid), x in side.items() if r == rn and (s is None or x == s)}

    # ================= dano (limitado à vida restante) =================
    h = _ev(p, "player_hurt", other=["total_rounds_played"])
    h = h[h["tick"] > start_tick].sort_values("tick")
    hp: dict[tuple[int, str], int] = {}
    hurts = []  # (rn, tick, att, vic, real, weapon)
    for e in h.itertuples():
        rn = round_of(int(e.tick))
        att, vic = _sid(e.attacker_steamid), _sid(e.user_steamid)
        if not rn or not vic:
            continue
        before = hp.get((rn, vic), 100)
        real = min(int(e.dmg_health), before)
        hp[(rn, vic)] = int(e.health)
        if att and att != vic and side.get((rn, att)) != side.get((rn, vic)):
            hurts.append((rn, int(e.tick), att, vic, real, e.weapon))

    # ================= cegueiras =================
    blinds = _ev(p, "player_blind")
    blinds = blinds[blinds["tick"] > start_tick]
    blind_rows = [(int(b.tick), int(b.entityid), _sid(b.attacker_steamid), _sid(b.user_steamid), float(b.blind_duration))
                  for b in blinds.itertuples()]
    if not blind_rows:
        blind_rows = _blinds_from_ticks(p, start_tick)

    # ================= granadas =================
    grenades = _grenades(p, start_tick, round_of, side, blind_rows, hurts)

    # ================= abates =================
    k = _ev(p, "player_death", player=["X", "Y", "Z", "last_place_name"])
    k = k[k["tick"] > start_tick].copy()
    k["rn"] = [round_of(int(t)) for t in k["tick"]]
    k = k[k["rn"] > 0].sort_values("tick")
    death_ticks = sorted({int(t) for t in k["tick"]})
    pos_at: dict[int, dict[str, tuple]] = defaultdict(dict)
    if death_ticks:
        dp = p.parse_ticks(["X", "Y", "Z", "is_alive"], ticks=death_ticks)
        for r in dp.itertuples():
            if r.is_alive:
                pos_at[int(r.tick)][str(r.steamid)] = (r.X, r.Y, r.Z)
    held = _held_at_death(p, death_ticks)
    duel = _duels(p, [(int(t), _sid(a), _sid(v)) for t, a, v in zip(k["tick"], k["attacker_steamid"], k["user_steamid"])], hurts)

    stats = defaultdict(lambda: defaultdict(int))
    pr = defaultdict(lambda: defaultdict(int))     # (rn, sid) -> kills/deaths/assists/damage
    kast_rounds: dict[str, set] = defaultdict(set)
    kills_rows: list[list] = []
    clutches = []
    by_round = defaultdict(list)
    for r in k.itertuples():
        by_round[r.rn].append(r)

    for rn in range(1, n_rounds + 1):
        evs = by_round.get(rn, [])
        alive = {s: players_in(rn, s) for s in ("CT", "T")}
        in_clutch: dict[str, dict] = {}
        deaths_at: dict[str, tuple[int, str]] = {}
        round_kills = defaultdict(int)
        r_start = freeze[rn - 1]
        for idx, e in enumerate(evs):
            tick = int(e.tick)
            att, vic, ast = _sid(e.attacker_steamid), _sid(e.user_steamid), _sid(e.assister_steamid)
            a_s, v_s = side.get((rn, att)), side.get((rn, vic))
            teamkill = bool(att) and a_s == v_s
            valid_kill = bool(att) and att != vic and not teamkill
            # --- contexto da morte (antes de tirar a vítima dos vivos)
            mates = alive.get(v_s, set()) - {vic} if v_s else set()
            enemies = alive.get("T" if v_s == "CT" else "CT", set()) if v_s else set()
            pos = pos_at.get(tick, {})
            vpos = (e.user_X, e.user_Y, e.user_Z)
            mate_d = [_dist(vpos, pos[mt]) for mt in mates if mt in pos and not pd.isna(vpos[0])]
            util_before = sum(1 for g in grenades if g["round_num"] == rn and g["thrower"] == vic
                              and tick - 20 * TICKRATE <= g["throw_tick"] <= tick)
            vblind = max((t + d * TICKRATE - tick) / TICKRATE for t, _, _, u, d in blind_rows
                         if u == vic and t <= tick <= t + d * TICKRATE) if any(
                u == vic and t <= tick <= t + d * TICKRATE for t, _, _, u, d in blind_rows) else 0.0
            sources = {a for (r2, t, a, v, _, _) in hurts if r2 == rn and v == vic and tick - 5 * TICKRATE <= t <= tick}
            # --- estatísticas
            if vic:
                stats[vic]["deaths"] += 1
                pr[(rn, vic)]["deaths"] += 1
            if valid_kill:
                stats[att]["kills"] += 1
                stats[att]["hs"] += bool(e.headshot)
                pr[(rn, att)]["kills"] += 1
                round_kills[att] += 1
                kast_rounds[att].add(rn)
            if ast and side.get((rn, ast)) != v_s:
                stats[ast]["assists"] += 1
                pr[(rn, ast)]["assists"] += 1
                kast_rounds[ast].add(rn)
                if bool(e.assistedflash):
                    stats[ast]["flash_assists"] += 1
            first = idx == 0
            if first and valid_kill:
                stats[att]["fk"] += 1
                stats[vic]["fd"] += 1
            is_trade = 0
            for dead, (t0, killer) in deaths_at.items():
                if killer == vic and tick - t0 <= TRADE_TICKS and side.get((rn, dead)) == a_s and valid_kill:
                    is_trade = 1
                    stats[att]["trade_kills"] += 1
                    stats[dead]["traded"] += 1
                    kast_rounds[dead].add(rn)
                    for row in kills_rows:
                        if row[1] == rn and row[5] == dead and row[2] == t0:
                            row[16] = 1
            deaths_at[vic] = (tick, att)
            apos = (e.attacker_X, e.attacker_Y, e.attacker_Z)
            att_dist = _dist(apos, vpos) if att and not pd.isna(apos[0]) and not pd.isna(vpos[0]) else None
            kills_rows.append([
                match_id, rn, tick, round((tick - r_start) / TICKRATE, 1), att, vic, ast, e.weapon,
                int(bool(e.headshot)), a_s, v_s, _num(e.attacker_X), _num(e.attacker_Y), _num(e.user_X), _num(e.user_Y),
                int(first), 0, is_trade, _num(e.attacker_Z), _num(e.user_Z), _num(att_dist), len(mates), len(enemies),
                _num(min(mate_d)) if mate_d else None, sum(1 for d in mate_d if d <= NEAR), util_before,
                round(vblind, 1), len(sources), int(bool(e.assistedflash)), int(bool(e.thrusmoke)),
                int(e.penetrated or 0), int(bool(e.attackerblind)),
                _place(getattr(e, "attacker_last_place_name", None)), _place(getattr(e, "user_last_place_name", None)),
                *held.get((tick, vic), (None, None)), *duel.get((tick, vic), (None, None, None))])
            # --- vivos e clutch
            if v_s and vic in alive.get(v_s, set()):
                alive[v_s].discard(vic)
            for s in ("CT", "T"):
                other = "T" if s == "CT" else "CT"
                if len(alive[s]) == 1 and alive[other]:
                    (sid,) = alive[s]
                    if sid not in in_clutch:
                        in_clutch[sid] = {"vs": len(alive[other]), "tick": tick, "kills0": round_kills[sid], "side": s}
        winner = ends.loc[rn - 1, "winner"]
        for sid, c in in_clutch.items():
            won = int(winner == c["side"])
            clutches.append((match_id, rn, sid, c["side"], c["vs"], won, round_kills[sid] - c["kills0"], c["tick"]))
            stats[sid]["clutches"] += 1
            stats[sid]["clutches_won"] += won
        for sid, n in round_kills.items():
            if n >= 3:
                stats[sid]["multi"] += 1
        for sid in players_in(rn) - set(deaths_at):  # sobreviveu
            kast_rounds[sid].add(rn)

    for rn, t, att, vic, real, wpn in hurts:
        stats[att]["damage"] += real
        pr[(rn, att)]["damage"] += real
        if wpn in UTIL_WEAPONS:
            stats[att]["util"] += real
    for g in grenades:
        if g["type"] == "flash":
            stats[g["thrower"]]["flashes"] += 1
            stats[g["thrower"]]["enemies_flashed"] += g["enemies_blinded"]

    # ================= rounds e economia =================
    rounds = []
    sa = sb = 0
    for i, r in ends.iterrows():
        rn = i + 1
        ws = r["winner"]
        a_won = ws == a_side(rn)
        sa, sb = sa + a_won, sb + (not a_won)
        ea = [equip[(rn, s)] for s in team_a if (rn, s) in side]
        eb = [equip[(rn, s)] for s in team_b if (rn, s) in side]
        avg_a = sum(ea) / len(ea) if ea else 0
        avg_b = sum(eb) / len(eb) if eb else 0
        rounds.append((match_id, rn, ws, r["reason"], "A" if a_won else "B", a_side(rn), sa, sb, freeze[i],
                       end_ticks[i], sum(ea), sum(eb), buy_type(avg_a, rn), buy_type(avg_b, rn)))

    player_rounds = []
    for (rn, sid), s in side.items():
        d = pr[(rn, sid)]
        player_rounds.append((match_id, rn, sid, s, equip.get((rn, sid)), money.get((rn, sid)), d["kills"],
                              d["deaths"], d["assists"], d["damage"], int(rn in kast_rounds[sid])))

    # ================= bomba =================
    bomb_rows = _bomb(p, match_id, start_tick, round_of)
    try:
        from .radar import overview
        ov = overview(m["map"] or "") or {}
        if "bombA" in ov and "bombB" in ov:
            site_of = {}
            for r in bomb_rows:
                if r[2] == "plantou" and r[6] is not None:
                    site_of[r[1]] = min("AB", key=lambda s: _dist((r[6], r[7]), ov[f"bomb{s}"]))
            bomb_rows = [r[:5] + (site_of.get(r[1], ""),) + r[6:] for r in bomb_rows]
    except Exception:
        log.warning("não consegui identificar os bombsites", exc_info=True)

    # ================= replay (posições) =================
    replays = _replays(p, match_id, n_rounds, freeze, end_ticks, side, names)

    # ================= jogadores =================
    players = []
    for sid in team_a | team_b:
        s = stats[sid]
        played = sum(1 for (rn, x) in side if x == sid)
        if not played:
            continue
        kills, deaths = s["kills"], s["deaths"]
        adr = s["damage"] / played
        kast = 100 * len(kast_rounds[sid]) / played
        # nota simples (estilo HLTV 1.0 aproximado), só para ordenar/comparar
        rating = round((kills / played) / 0.679 * 0.35 + (played - deaths) / played / 0.317 * 0.25
                       + adr / 80 * 0.25 + kast / 100 / 0.70 * 0.15, 2)
        players.append((match_id, sid, names.get(sid, sid), "A" if sid in team_a else "B",
                        "CT" if sid in team_a else "T", kills, deaths, s["assists"], s["damage"], round(adr, 1),
                        round(100 * s["hs"] / kills, 1) if kills else 0.0, round(kast, 1), s["fk"], s["fd"],
                        s["trade_kills"], s["traded"], s["util"], played, rating, s["flashes"],
                        s["enemies_flashed"], s["flash_assists"], s["clutches_won"], s["clutches"], s["multi"],
                        *ranks.get(sid, (0, None))))

    # ================= tiros (mira) =================
    try:
        shots = aim.extract(p, match_id, round_of, side)
    except Exception:
        log.exception("Falha ao ler os tiros da partida %s", match_id)
        shots = []

    # ================= grava =================
    with db.tx() as c:
        for t in TABLES:
            c.execute(f"DELETE FROM {t} WHERE match_id=?", (match_id,))
        ins = lambda t, rows: rows and c.executemany(  # noqa: E731
            f"INSERT INTO {t} VALUES({','.join('?' * len(rows[0]))})", rows)
        ins("demo_players", players)
        ins("demo_rounds", rounds)
        ins("demo_player_rounds", player_rounds)
        ins("demo_kills", kills_rows)
        ins("demo_clutches", clutches)
        ins("demo_bomb", bomb_rows)
        ins("demo_replays", replays)
        aim.save(match_id, shots, c)
        ins("demo_grenades", [(match_id, g["round_num"], g["thrower"], g["side"], g["type"], g["throw_tick"],
                               g["det_tick"], g["end_tick"], g["tx"], g["ty"], g["x"], g["y"], g["z"],
                               g["enemies_blinded"], g["mates_blinded"], g["blind_time"], g["damage"], g["hits"],
                               json.dumps(g["blinded"]), json.dumps(g["path"])) for g in grenades])
        c.execute("""UPDATE matches SET team_a=?, team_b=?, score_a=?, score_b=?, rounds_total=?, analyzed_at=?,
                     analysis_version=?, status='analisada', note=NULL WHERE id=?""",
                  (name_a, name_b, sa, sb, n_rounds, db.now(), VERSION, match_id))
    from .config import settings
    me = settings.steam_id64 or db.kv_get("steamid")
    if me:
        set_me(me, match_id)
    log.info("Partida %s analisada: %s %s x %s %s, %d rounds, %d granadas", match_id, name_a, sa, sb, name_b,
             n_rounds, len(grenades))


NADES = {"Flashbang", "Smoke Grenade", "High Explosive Grenade", "Molotov", "Incendiary Grenade", "Decoy Grenade"}


def _held_at_death(p, death_ticks) -> dict[tuple[int, str], tuple[str | None, int]]:
    """Arma na mão de quem morreu (no tick anterior à morte) e quantas granadas ainda tinha guardadas."""
    if not death_ticks:
        return {}
    try:
        df = p.parse_ticks(["active_weapon_name", "inventory"], ticks=[t - 1 for t in death_ticks])
    except Exception:
        return {}
    out = {}
    for r in df.itertuples():
        w = r.active_weapon_name if isinstance(r.active_weapon_name, str) else None
        inv = list(r.inventory) if r.inventory is not None and not isinstance(r.inventory, float) else []
        out[(int(r.tick) + 1, str(r.steamid))] = (w, sum(1 for x in inv if x in NADES))
    return out


SPEED_WIN = 8     # velocidade de quem morreu: 1/8 s antes do 1º dano (jiggle quase se anula, corrida não)
SWING_WIN = 32    # velocidade de quem matou: 0,5 s antes do 1º dano (peek rápido = "ferrari peek")
FIRST_HIT = 10 * TICKRATE


def _duels(p, kills, hurts) -> dict[tuple[int, str], tuple[int | None, int | None, int | None]]:
    """Para cada morte: velocidade da vítima e do matador e o ângulo entre a mira da vítima e o matador,
    no 1º dano que o matador deu nela (o começo do duelo, não o tiro final)."""
    first: dict[tuple[int, str], tuple[int, str]] = {}
    for tick, att, vic in kills:
        if not att or not vic or att == vic:
            continue
        hits = [t for (_, t, a, v, _, _) in hurts if a == att and v == vic and tick - FIRST_HIT <= t <= tick]
        first[(tick, vic)] = (min(hits) if hits else tick, att)
    if not first:
        return {}
    ticks = sorted({t for f, _ in first.values() for t in (f - 1, f - 1 - SPEED_WIN, f - 1 - SWING_WIN)})
    try:
        df = p.parse_ticks(["X", "Y", "yaw"], ticks=ticks)
    except Exception:
        return {}
    st = {(int(r.tick), str(r.steamid)): (r.X, r.Y, r.yaw) for r in df.itertuples()}

    def speed(t, sid, win):
        a, b = st.get((t, sid)), st.get((t - win, sid))
        if not a or not b or pd.isna(a[0]) or pd.isna(b[0]):
            return None
        return int(round(math.hypot(a[0] - b[0], a[1] - b[1]) / (win / TICKRATE)))

    out = {}
    for (tick, vic), (f, att) in first.items():
        t = f - 1
        v, a = st.get((t, vic)), st.get((t, att))
        ang = None
        if v and a and not any(pd.isna(x) for x in (*v, *a[:2])):
            d = math.degrees(math.atan2(a[1] - v[1], a[0] - v[0]))
            ang = int(round(abs((d - v[2] + 180) % 360 - 180)))
        out[(tick, vic)] = (speed(t, vic, SPEED_WIN), speed(t, att, SWING_WIN), ang)
    return out


def _blinds_from_ticks(p, start_tick) -> list[tuple]:
    """Demos de campeonato (GOTV) não gravam o evento player_blind. Aqui a cegueira vem do estado dos jogadores:
    quem teve o flash_duration renovado no instante em que a flash explodiu foi cegado por ela."""
    det = _ev(p, "flashbang_detonate")
    if det.empty or "entityid" not in det.columns:
        return []
    det = det[det["tick"] > start_tick]
    flashes = [(int(r.tick), int(r.entityid), _sid(r.user_steamid)) for r in det.itertuples()]
    if not flashes:
        return []
    ticks = sorted({t + k for t, _, _ in flashes for k in (-1, 1)})
    try:
        df = p.parse_ticks(["flash_duration"], ticks=ticks)
    except Exception:
        return []
    dur = {(int(r.tick), str(r.steamid)): float(r.flash_duration or 0) for r in df.itertuples()}
    sids = {str(s) for s in df["steamid"].unique()}
    out = []
    for t, ent, thrower in flashes:
        for sid in sids:
            before, after = dur.get((t - 1, sid), 0.0), dur.get((t + 1, sid), 0.0)
            if after > 0 and abs(after - before) > 1e-3:
                out.append((t, ent, thrower, sid, after))
    return out


def _grenades(p, start_tick, round_of, side, blind_rows, hurts) -> list[dict]:
    g = p.parse_grenades()
    g = g[g["grenade_type"].isin(NADE.keys()) & g["x"].notna() & (g["tick"] > start_tick)]
    g = g.sort_values(["grenade_entity_id", "tick"])
    det = {}
    for typ, ev in DETONATE.items():
        try:
            d = _ev(p, ev)
            det[typ] = [(int(r.tick), _sid(r.user_steamid), int(r.entityid), r.x, r.y, r.z) for r in d.itertuples()
                        if r.tick > start_tick]
        except Exception:
            det[typ] = []
    expire = {}
    for typ, ev in (("smoke", "smokegrenade_expired"), ("molotov", "inferno_expire")):
        try:
            expire[typ] = [(int(r.tick), int(r.entityid)) for r in _ev(p, ev).itertuples()]
        except Exception:
            expire[typ] = []

    out = []
    for (ent, sid), grp in g.groupby(["grenade_entity_id", "steamid"], sort=False):
        ticks = grp["tick"].to_numpy()
        cuts = [0] + [i for i in range(1, len(ticks)) if ticks[i] - ticks[i - 1] > 32] + [len(ticks)]
        for a, b in zip(cuts, cuts[1:]):
            seg = grp.iloc[a:b]
            typ = NADE[seg["grenade_type"].iloc[0]]
            thrower = _sid(sid)
            t0, t1 = int(seg["tick"].iloc[0]), int(seg["tick"].iloc[-1])
            rn = round_of(t0)
            if not rn:
                continue
            s = side.get((rn, thrower))
            # detonação: evento do mesmo tipo/arremessador mais próximo depois do voo
            cands = [d for d in det.get(typ, []) if d[1] == thrower and t0 <= d[0] <= t1 + 3 * TICKRATE]
            dd = min(cands, key=lambda d: abs(d[0] - t1)) if cands else None
            det_tick = dd[0] if dd else t1
            x, y, z = (dd[3], dd[4], dd[5]) if dd else (seg["x"].iloc[-1], seg["y"].iloc[-1], seg["z"].iloc[-1])
            end_tick = det_tick + int(EFFECT_SECS[typ] * TICKRATE)
            if dd and typ in expire:
                ex = [t for t, e in expire[typ] if e == dd[2] and t > det_tick]
                if ex:
                    end_tick = min(ex)
            blinded, eb, mb, btime = [], 0, 0, 0.0
            if typ == "flash" and dd:
                for bt, be, ba, bu, bdur in blind_rows:
                    if be == dd[2] and abs(bt - det_tick) <= 2 and bdur > 0:
                        enemy = side.get((rn, bu)) not in (None, s)
                        blinded.append({"sid": bu, "dur": round(bdur, 2), "enemy": enemy})
                        if bdur >= FLASH_MIN and bu != thrower:
                            if enemy:
                                eb += 1
                                btime += bdur
                            else:
                                mb += 1
            dmg, hit = 0, set()
            if typ == "he":
                for r2, t, att, vic, real, wpn in hurts:
                    if att == thrower and wpn == "hegrenade" and abs(t - det_tick) <= 8:
                        dmg += real
                        hit.add(vic)
            elif typ == "molotov":
                for r2, t, att, vic, real, wpn in hurts:
                    if att == thrower and wpn in ("inferno", "molotov", "incgrenade") and det_tick <= t <= end_tick + 64:
                        dmg += real
                        hit.add(vic)
            path = [[int(t), _num(px), _num(py)] for t, px, py in
                    seg[["tick", "x", "y"]].iloc[::4].itertuples(index=False)]
            path.append([t1, _num(seg["x"].iloc[-1]), _num(seg["y"].iloc[-1])])
            out.append({"round_num": rn, "thrower": thrower, "side": s, "type": typ, "throw_tick": t0,
                        "det_tick": det_tick, "end_tick": end_tick, "tx": _num(seg["x"].iloc[0]),
                        "ty": _num(seg["y"].iloc[0]), "x": _num(x), "y": _num(y), "z": _num(z),
                        "enemies_blinded": eb, "mates_blinded": mb, "blind_time": round(btime, 1),
                        "damage": dmg, "hits": len(hit), "blinded": blinded, "path": path})
    # um molotov/ incendiária reaproveita dano por tick; evita contar o mesmo dano em dois fogos
    return sorted(out, key=lambda g: g["throw_tick"])


def _bomb(p, match_id, start_tick, round_of) -> list[tuple]:
    rows, plant_pos = [], {}
    evs = []
    for kind, ev in (("plantou", "bomb_planted"), ("desarmou", "bomb_defused"), ("explodiu", "bomb_exploded")):
        try:
            d = _ev(p, ev, player=["X", "Y"])
        except Exception:
            continue
        for r in d.itertuples():
            if r.tick > start_tick:
                evs.append((kind, int(r.tick), _sid(getattr(r, "user_steamid", "")), str(getattr(r, "site", "")),
                            getattr(r, "user_X", None), getattr(r, "user_Y", None)))
    for kind, tick, sid, site, x, y in sorted(evs, key=lambda e: e[1]):
        rn = round_of(tick)
        if not rn:
            continue
        if kind == "plantou":
            plant_pos[rn] = (x, y)
        if kind == "explodiu" or x is None or pd.isna(x):
            x, y = plant_pos.get(rn, (x, y))
        rows.append((match_id, rn, kind, tick, sid, site, _num(x), _num(y)))
    return rows


def _replays(p, match_id, n_rounds, freeze, end_ticks, side, names) -> list[tuple]:
    windows = []
    for i in range(n_rounds):
        stop = end_ticks[i] + 4 * TICKRATE
        if i + 1 < n_rounds:
            stop = min(stop, freeze[i + 1] - 1)
        windows.append(list(range(freeze[i], stop + 1, SAMPLE)))
    all_ticks = sorted({t for w in windows for t in w})
    df = p.parse_ticks(["X", "Y", "Z", "yaw", "health", "is_alive", "active_weapon_name", "has_defuser",
                        "flash_duration"], ticks=all_ticks)
    df = df[df["steamid"].astype(str).str.len() == 17]
    by_tick = {t: g for t, g in df.groupby("tick")}
    rows = []
    for i, w in enumerate(windows):
        rn = i + 1
        sids = sorted({sid for (r, sid) in side if r == rn}, key=lambda s: (side[(rn, s)], names.get(s, "")))
        weapons: list[str] = []
        widx: dict[str, int] = {}
        tracks = {s: {"sid": s, "name": names.get(s, s), "side": side[(rn, s)], "x": [], "y": [], "z": [],
                      "hp": [], "yaw": [], "w": [], "fl": []} for s in sids}
        for t in w:
            g = by_tick.get(t)
            rowmap = {str(r.steamid): r for r in g.itertuples()} if g is not None else {}
            for s in sids:
                r = rowmap.get(s)
                tr = tracks[s]
                if r is None or not r.is_alive:
                    for key in ("x", "y", "z", "yaw", "w", "fl"):
                        tr[key].append(None)
                    tr["hp"].append(0)
                    continue
                wn = r.active_weapon_name if isinstance(r.active_weapon_name, str) else ""
                if wn not in widx:
                    widx[wn] = len(weapons)
                    weapons.append(wn)
                tr["x"].append(_num(r.X))
                tr["y"].append(_num(r.Y))
                tr["z"].append(_num(r.Z))
                tr["hp"].append(int(r.health or 0))
                tr["yaw"].append(_num(r.yaw))
                tr["w"].append(widx[wn])
                tr["fl"].append(round(float(r.flash_duration or 0), 1))
        data = {"t0": w[0], "step": SAMPLE, "n": len(w), "tickrate": TICKRATE, "end_tick": end_ticks[i],
                "weapons": weapons, "players": list(tracks.values())}
        rows.append((match_id, rn, gzip.compress(json.dumps(data, separators=(",", ":")).encode())))
    return rows


def set_me(steamid: str, match_id: int | None = None) -> None:
    """Define qual jogador é você e recalcula resultado das partidas."""
    db.kv_set("steamid", steamid)
    rows = db.q("SELECT id, score_a, score_b FROM matches WHERE analyzed_at IS NOT NULL"
                + (" AND id=?" if match_id else ""), *([match_id] if match_id else []))
    with db.tx() as c:
        for m in rows:
            pl = c.execute("SELECT team, rating FROM demo_players WHERE match_id=? AND steamid=?",
                           (m["id"], steamid)).fetchone()
            if not pl:
                continue
            my, en = (m["score_a"], m["score_b"]) if pl["team"] == "A" else (m["score_b"], m["score_a"])
            res = "vitoria" if my > en else "derrota" if my < en else "empate"
            c.execute("UPDATE matches SET my_steamid=?, my_score=?, enemy_score=?, result=?, my_rating=? WHERE id=?",
                      (steamid, my, en, res, pl["rating"], m["id"]))
