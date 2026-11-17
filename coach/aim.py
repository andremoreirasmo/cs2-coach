"""Mira: cada tiro das demos (andando ou parado, posição no spray, se acertou e onde).

Tudo é calculado aqui, sem IA: os números são comparados com os outros jogadores das
suas próprias partidas ("o lobby"), e viram uma lista do que está bom e do que melhorar.
"""
from __future__ import annotations

import bisect
import logging
import math
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd

from . import db

log = logging.getLogger("coach.aim")
TICKRATE = 64

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_shots (
    match_id INTEGER, round_num INTEGER, tick INTEGER, steamid TEXT, weapon TEXT,
    speed INTEGER, moving INTEGER, air INTEGER, crouch INTEGER, scoped INTEGER,
    burst INTEGER, hit INTEGER, head INTEGER, dmg INTEGER, flick REAL, strafe TEXT, strafe_ms INTEGER
);
CREATE INDEX IF NOT EXISTS demo_shots_m ON demo_shots(match_id, steamid);
"""

# velocidade máxima de cada arma (unidades/s). Abaixo de 34% dela o tiro sai preciso.
MAX_SPEED = {
    "ak47": 215, "m4a1": 225, "m4a1_silencer": 225, "famas": 220, "galilar": 215, "aug": 220, "sg556": 210,
    "awp": 200, "ssg08": 230, "scar20": 215, "g3sg1": 215, "deagle": 230, "revolver": 180, "elite": 240,
    "glock": 240, "usp_silencer": 240, "hkp2000": 240, "p250": 240, "tec9": 240, "fiveseven": 240, "cz75a": 240,
    "mp9": 240, "mac10": 240, "mp7": 220, "mp5sd": 235, "ump45": 230, "p90": 230, "bizon": 240,
    "xm1014": 215, "nova": 220, "mag7": 225, "sawedoff": 210, "negev": 150, "m249": 195,
}
NAMES = {
    "ak47": "AK-47", "m4a1": "M4A4", "m4a1_silencer": "M4A1-S", "famas": "FAMAS", "galilar": "Galil", "aug": "AUG",
    "sg556": "SG 553", "awp": "AWP", "ssg08": "Scout", "deagle": "Desert Eagle", "glock": "Glock",
    "usp_silencer": "USP-S", "hkp2000": "P2000", "p250": "P250", "tec9": "Tec-9", "fiveseven": "Five-SeveN",
    "cz75a": "CZ75", "mp9": "MP9", "mac10": "MAC-10", "mp7": "MP7", "mp5sd": "MP5-SD", "ump45": "UMP-45",
    "p90": "P90", "bizon": "PP-Bizon", "elite": "Dual Berettas", "revolver": "R8", "xm1014": "XM1014",
    "nova": "Nova", "mag7": "MAG-7", "sawedoff": "Sawed-Off", "negev": "Negev", "m249": "M249",
    "scar20": "SCAR-20", "g3sg1": "G3SG1",
}
SPRAY = {"ak47", "m4a1", "m4a1_silencer", "famas", "galilar", "aug", "sg556", "mp9", "mac10", "mp7", "mp5sd",
         "ump45", "p90", "bizon", "negev", "m249"}
SNIPER = {"awp", "ssg08", "scar20", "g3sg1"}
# armas em que é preciso parar para acertar. Com SMG, pistola e escopeta atirar andando é normal: fica fora da conta.
STOP = {"ak47", "m4a1", "m4a1_silencer", "famas", "galilar", "aug", "sg556", "deagle", "revolver"} | SNIPER
BURST_GAP = 16  # tiros com até 0,25 s entre si são da mesma rajada
FLICK_BEFORE = 19  # ~0,3 s antes do primeiro tiro


def migrate() -> None:
    with db.tx() as c:
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(demo_shots)")}
        for col, typ in (("strafe", "TEXT"), ("strafe_ms", "INTEGER")):
            if col not in cols:
                c.execute(f"ALTER TABLE demo_shots ADD COLUMN {col} {typ}")


def _w(name) -> str:
    return str(name or "").removeprefix("weapon_")


def _ang(p1, y1, p2, y2) -> float:
    dy = abs((y1 - y2 + 180) % 360 - 180)
    return math.hypot(dy, p1 - p2)


def extract(p, match_id: int, round_of, side: dict) -> list[tuple]:
    """Uma linha por tiro de arma de fogo (sem faca, granada, C4 ou zeus)."""
    try:
        f = p.parse_event("weapon_fire", player=["velocity_X", "velocity_Y", "velocity_Z", "ducking",
                                                 "is_scoped", "pitch", "yaw"])
    except Exception:
        return []
    if not isinstance(f, pd.DataFrame) or not len(f):
        return []
    f = f.assign(w=f["weapon"].map(_w))
    f = f[f["w"].isin(MAX_SPEED.keys())].sort_values("tick")
    try:
        h = p.parse_event("player_hurt")
    except Exception:
        h = None
    hurts = defaultdict(list)  # atirador -> [(tick, arma, vítima, região, dano)]
    if isinstance(h, pd.DataFrame) and len(h):
        for r in h.itertuples():
            hurts[str(r.attacker_steamid)].append((int(r.tick), _w(r.weapon), str(r.user_steamid),
                                                   str(r.hitgroup), int(r.dmg_health or 0)))

    shots = []  # [rn, tick, sid, w, speed, moving, air, crouch, scoped, burst, hit, head, dmg, pitch, yaw]
    last = {}
    for r in f.itertuples():
        sid, t = str(r.user_steamid), int(r.tick)
        rn = round_of(t)
        if not rn or len(sid) != 17:
            continue
        w = r.w
        vx, vy, vz = (float(getattr(r, k) or 0) for k in ("user_velocity_X", "user_velocity_Y", "user_velocity_Z"))
        speed = math.hypot(vx, vy)
        air = abs(vz) > 60
        moving = speed > MAX_SPEED[w] * 0.34 or air
        prev = last.get(sid)
        burst = prev[1] + 1 if prev and prev[2] == w and t - prev[0] <= BURST_GAP else 1
        last[sid] = (t, burst, w)
        shots.append([rn, t, sid, w, round(speed), int(moving), int(air), int(bool(r.user_ducking)),
                      int(bool(r.user_is_scoped)), burst, 0, 0, 0, float(r.user_pitch or 0), float(r.user_yaw or 0)])

    # acerto: dano da mesma arma em até 2 ticks depois do tiro, num inimigo (vai pro tiro mais recente)
    by_sid = defaultdict(list)
    for i, s in enumerate(shots):
        by_sid[s[2]].append(i)
    for sid, idx in by_sid.items():
        ticks = [shots[i][1] for i in idx]
        for t, w, vic, grp, dmg in hurts.get(sid, []):
            if vic == sid or grp == "generic":
                continue
            k = bisect.bisect_right(ticks, t) - 1
            if k < 0:
                continue
            s = shots[idx[k]]
            # o dano às vezes vem com outro nome (M4A1-S = m4a1, USP-S = hkp2000): basta ser arma de fogo
            if t - s[1] > 2 or w not in MAX_SPEED:
                continue
            rn = s[0]
            if side.get((rn, vic)) == side.get((rn, sid)):
                continue  # aliado
            s[10] = 1
            s[11] = s[11] or int(grp == "head")
            s[12] += dmg

    # ajuste da mira antes do 1º tiro de cada rajada que acertou: quanto a mira andou nos 0,3 s antes
    firsts = [s for s in shots if s[9] == 1 and s[10] and s[1] > FLICK_BEFORE]
    flick = {}
    if firsts:
        try:
            ang = p.parse_ticks(["pitch", "yaw"], ticks=sorted({s[1] - FLICK_BEFORE for s in firsts}))
            look = {(int(a.tick), str(a.steamid)): (float(a.pitch), float(a.yaw)) for a in ang.itertuples()}
            for s in firsts:
                a = look.get((s[1] - FLICK_BEFORE, s[2]))
                if a:
                    flick[(s[1], s[2])] = round(min(180.0, _ang(a[0], a[1], s[13], s[14])), 1)
        except Exception:
            log.warning("Não deu para medir o ajuste da mira")
    try:
        strafe = _strafes(p, shots)
    except Exception:
        log.exception("Não deu para medir o counter-strafe")
        strafe = {}
    return [(match_id, s[0], s[1], s[2], s[3], s[4], s[5], s[6], s[7], s[8], s[9], s[10], s[11], s[12],
             flick.get((s[1], s[2])), *strafe.get((s[1], s[2]), (None, None))) for s in shots]


# ---------------------------------------------------------------- counter-strafe
# No 1º tiro de cada rajada (rifle, Deagle, sniper), olha as teclas e a velocidade dos 0,375 s antes:
#   parado   - já estava parado, não precisou frear
#   ok_cs    - freou com a tecla contrária e atirou já parado (o certo)
#   ok_solto - só soltou a tecla e esperou parar (funciona, mas é mais lento)
#   cedo     - apertou a tecla contrária, mas atirou antes de parar
#   demais   - segurou a tecla contrária tempo demais: já estava andando para o outro lado
#   andando  - não freou: atirou correndo
# strafe_ms: cedo = quantos ms antes de ficar preciso; ok_cs/ok_solto = quanto esperou depois de parar;
#            demais = quanto tempo segurou a tecla contrária.
STRAFE_BEFORE, STRAFE_AFTER = 24, 12
OPP = {"LEFT": "RIGHT", "RIGHT": "LEFT", "FORWARD": "BACK", "BACK": "FORWARD"}
STRAFES = ("parado", "ok_cs", "ok_solto", "cedo", "demais", "andando")


def _strafes(p, shots) -> dict[tuple[int, str], tuple[str, int | None]]:
    firsts = [s for s in shots if s[9] == 1 and not s[6] and s[3] in STOP and s[1] > STRAFE_BEFORE]
    if not firsts:
        return {}
    ticks = sorted({t for s in firsts for t in range(s[1] - STRAFE_BEFORE, s[1] + STRAFE_AFTER + 1)})
    df = p.parse_ticks(["X", "Y", "FORWARD", "BACK", "LEFT", "RIGHT"], ticks=ticks)
    st = {(int(r.tick), str(r.steamid)): r for r in df.itertuples()}
    ms = lambda n: int(round(n * 1000 / TICKRATE))  # noqa: E731
    out = {}
    for s in firsts:
        t, sid = s[1], s[2]
        rows = [st.get((x, sid)) for x in range(t - STRAFE_BEFORE, t + STRAFE_AFTER + 1)]
        shot = STRAFE_BEFORE  # índice do tiro em rows
        if any(r is None or pd.isna(r.X) for r in rows[:shot + 1]):
            continue
        vel = [None] + [((b.X - a.X) * TICKRATE, (b.Y - a.Y) * TICKRATE) if a is not None and b is not None
                        and not pd.isna(b.X) else None for a, b in zip(rows, rows[1:])]
        sp = [math.hypot(*v) if v else None for v in vel]
        thr = MAX_SPEED[s[3]] * 0.34
        pk = max(range(1, shot + 1), key=lambda i: sp[i])
        if sp[pk] < thr:
            out[(t, sid)] = ("parado", None)
            continue
        held = {k for k in OPP if bool(getattr(rows[pk], k))}
        counter = next((i for i in range(pk, shot + 1) if any(bool(getattr(rows[i], OPP[k])) for k in held)), None)
        acc = next((i for i in range(pk, shot + 1) if sp[i] <= thr), None)
        dot = vel[shot][0] * vel[pk][0] + vel[shot][1] * vel[pk][1]
        if sp[shot] <= thr:
            out[(t, sid)] = ("ok_cs" if counter is not None else "ok_solto", ms(shot - acc) if acc is not None else None)
        elif counter is not None and dot < 0:
            out[(t, sid)] = ("demais", ms(shot - counter))
        elif counter is not None:
            late = next((i for i in range(shot + 1, len(rows)) if sp[i] is not None and sp[i] <= thr), None)
            out[(t, sid)] = ("cedo", ms(late - shot) if late is not None else None)
        else:
            out[(t, sid)] = ("andando", None)
    return out


def save(match_id: int, rows: list[tuple], c=None) -> None:
    def go(cur):
        cur.execute("DELETE FROM demo_shots WHERE match_id=?", (match_id,))
        # sem tiro nenhum: grava uma linha vazia para marcar a partida como lida
        data = rows or [(match_id, 0, 0, "", "", 0, 0, 0, 0, 0, 0, 0, 0, 0, None, None, None)]
        if data:
            cur.executemany(f"INSERT INTO demo_shots VALUES({','.join('?' * 17)})", data)
    if c is not None:
        go(c)
    else:
        with db.tx() as cur:
            go(cur)


def fill(match_id: int) -> None:
    """Tiros das partidas analisadas antes desta função existir (lê só os eventos de tiro e dano)."""
    from demoparser2 import DemoParser
    migrate()
    r = db.q1("SELECT d.path FROM matches m JOIN demos d ON d.id=m.demo_id WHERE m.id=?", match_id)
    if not r or not Path(r["path"]).exists():
        return
    rounds = db.q("SELECT round_num, start_tick, end_tick FROM demo_rounds WHERE match_id=? ORDER BY round_num", match_id)
    if not rounds:
        return
    starts = [x["start_tick"] for x in rounds]
    n = len(rounds)

    def round_of(t):
        i = bisect.bisect_right(starts, t)
        return i if 1 <= i <= n else 0
    side = {(x["round_num"], x["steamid"]): x["side"]
            for x in db.q("SELECT round_num, steamid, side FROM demo_player_rounds WHERE match_id=?", match_id)}
    rows = extract(DemoParser(r["path"]), match_id, round_of, side)
    save(match_id, rows)


def missing() -> list[int]:
    migrate()
    return [r["id"] for r in db.q("""SELECT id FROM matches WHERE analyzed_at IS NOT NULL
                                     AND id NOT IN (SELECT DISTINCT match_id FROM demo_shots)""")]


# ---------------------------------------------------------------- estatísticas
def _pct(a, b):
    return round(100 * a / b, 1) if b else None


def _summary(rows) -> dict:
    """rows: (weapon, moving, air, burst, hit, head, flick, scoped)"""
    n = len(rows)
    hits = sum(r[4] for r in rows)
    first = [r for r in rows if r[3] == 1 and r[0] not in SNIPER]
    spray = [r for r in rows if r[0] in SPRAY]
    stop = [r for r in rows if r[0] in STOP]
    mv = [r for r in stop if r[1]]
    st = [r for r in stop if not r[1]]
    fl = [r[6] for r in rows if r[6] is not None]
    by = lambda a, b: [r for r in spray if a <= r[3] <= b]  # noqa: E731
    return {
        "tiros": n, "precisao": _pct(hits, n), "hs": _pct(sum(r[5] for r in rows), hits),
        "primeiro": _pct(sum(r[4] for r in first), len(first)),
        "andando": _pct(len(mv), len(stop)), "prec_andando": _pct(sum(r[4] for r in mv), len(mv)),
        "prec_parado": _pct(sum(r[4] for r in st), len(st)),
        "no_ar": _pct(sum(r[2] for r in rows), n),
        "spray_ini": _pct(sum(r[4] for r in by(2, 3)), len(by(2, 3))),
        "spray_meio": _pct(sum(r[4] for r in by(4, 7)), len(by(4, 7))),
        "spray_fim": _pct(sum(r[4] for r in by(8, 99)), len(by(8, 99))),
        "rajada_longa": _pct(sum(1 for r in spray if r[3] == 8), sum(1 for r in spray if r[3] == 1)),
        "ajuste": round(statistics.median(fl), 1) if len(fl) >= 5 else None,
    }


def _strafe_summary(rows) -> dict | None:
    """rows: (strafe, strafe_ms) dos 1ºs tiros. % de cada caso entre os que precisaram frear, e os tempos típicos."""
    rows = [r for r in rows if r[0]]
    moved = [r for r in rows if r[0] != "parado"]
    if len(moved) < 10:
        return None
    med = lambda k: (lambda v: int(statistics.median(v)) if len(v) >= 3 else None)(  # noqa: E731
        [r[1] for r in moved if r[0] == k and r[1] is not None])
    return {"primeiros": len(rows), "freou": len(moved), "parado": _pct(len(rows) - len(moved), len(rows)),
            **{k: _pct(sum(1 for r in moved if r[0] == k), len(moved)) for k in STRAFES if k != "parado"},
            "ms_cedo": med("cedo"), "ms_espera": med("ok_cs"), "ms_demais": med("demais")}


def _strafe_verdicts(me: dict | None, lob: dict | None, label: str = "lobby") -> list[dict]:
    if not me or not lob:
        return []
    out = []
    if me["cedo"] - lob["cedo"] >= 4:
        out.append({"tipo": "melhorar", "peso": me["cedo"] - lob["cedo"] + 6, "titulo": "Atira antes de parar",
                    "texto": f"Em {me['cedo']:.0f}% dos duelos em que precisou frear você apertou a tecla contrária, mas atirou ainda em movimento ({label}: {lob['cedo']:.0f}%)."
                    + (f" Faltaram cerca de {me['ms_cedo']} ms para parar." if me.get("ms_cedo") else ""),
                    "treino": "O counter-strafe está certo; falta esperar o boneco parar. No aim_botz, faça strafe-tecla contrária-tiro bem devagar e vá acelerando."})
    if me["demais"] - lob["demais"] >= 3:
        out.append({"tipo": "melhorar", "peso": me["demais"] - lob["demais"] + 4, "titulo": "Segura a tecla contrária demais",
                    "texto": f"Em {me['demais']:.0f}% dos casos você já estava andando para o outro lado quando atirou ({label}: {lob['demais']:.0f}%)."
                    + (f" Segurou a tecla contrária cerca de {me['ms_demais']} ms." if me.get("ms_demais") else ""),
                    "treino": "A tecla contrária é só um toque rápido. Treine soltar a tecla de movimento e tocar a outra ao mesmo tempo."})
    if me["andando"] - lob["andando"] >= 4:
        out.append({"tipo": "melhorar", "peso": me["andando"] - lob["andando"] + 4, "titulo": "Não freia antes de atirar",
                    "texto": f"Em {me['andando']:.0f}% dos casos você atirou sem frear ({label}: {lob['andando']:.0f}%).",
                    "treino": "Antes de cada tiro: soltar a tecla de movimento e tocar a contrária."})
    good = me["ok_cs"] + me["ok_solto"] - lob["ok_cs"] - lob["ok_solto"]
    if good >= 4:
        out.append({"tipo": "bom", "peso": good, "titulo": "Bom counter-strafe",
                    "texto": f"Em {me['ok_cs'] + me['ok_solto']:.0f}% dos duelos em que precisou frear você atirou já parado ({label}: {lob['ok_cs'] + lob['ok_solto']:.0f}%)."})
    return out


def _curve(rows, weapons) -> list[dict]:
    out = []
    for i in range(1, 13):
        sel = [r for r in rows if r[0] in weapons and (r[3] == i if i < 12 else r[3] >= 12)]
        out.append({"bala": i if i < 12 else "12+", "precisao": _pct(sum(r[4] for r in sel), len(sel)), "n": len(sel)})
    return out


def _verdicts(me: dict, lob: dict, label: str = "lobby") -> list[dict]:
    """O que está bom e o que melhorar, comparando com o lobby. Ordena pelo tamanho da diferença."""
    out = []

    def add(kind, peso, titulo, texto, treino=None):
        out.append({"tipo": kind, "peso": round(peso, 1), "titulo": titulo, "texto": texto, "treino": treino})

    def d(k):
        return None if me.get(k) is None or lob.get(k) is None else me[k] - lob[k]

    x = d("andando")
    if x is not None:
        if x > 3 or (me["andando"] or 0) > 30:
            add("melhorar", abs(x) + 4, "Você atira andando",
                f"{me['andando']:.0f}% dos seus tiros de rifle saem com você em movimento ({label}: {lob['andando']:.0f}%). "
                f"Andando você acerta {me['prec_andando'] or 0:.0f}%, parado {me['prec_parado'] or 0:.0f}%.",
                "Counter-strafe: solte a tecla e toque a do lado oposto antes de atirar. Treine no aim_botz andando de um lado pro outro e só atirando parado.")
        elif x < -3:
            add("bom", abs(x), "Você para antes de atirar",
                f"Só {me['andando']:.0f}% dos tiros saem em movimento ({label}: {lob['andando']:.0f}%). Bom counter-strafe.")
    x = d("primeiro")
    if x is not None:
        if x < -2:
            add("melhorar", abs(x) * 1.5, "Primeira bala erra mais que o normal",
                f"Seu primeiro tiro acerta {me['primeiro']:.0f}% ({label}: {lob['primeiro']:.0f}%).",
                "Mira parada na altura da cabeça antes do duelo e primeiro tiro com calma. Treine taps no aim_botz e no Yprac.")
        elif x > 2:
            add("bom", abs(x) * 1.5, "Primeira bala precisa",
                f"Seu primeiro tiro acerta {me['primeiro']:.0f}% ({label}: {lob['primeiro']:.0f}%).")
    sm, sl = me.get("spray_meio"), lob.get("spray_meio")
    if sm is not None and sl is not None:
        if sm < sl - 3:
            add("melhorar", (sl - sm) * 1.3, "O spray perde controle",
                f"Da 4ª à 7ª bala você acerta {sm:.0f}% ({label}: {sl:.0f}%). "
                f"Depois da 8ª: {me.get('spray_fim') or 0:.0f}% ({label}: {lob.get('spray_fim') or 0:.0f}%).",
                "Treine o padrão do spray da AK e da M4 num mapa de recoil (workshop) e prefira rajadas curtas de longe.")
        elif sm > sl + 3:
            add("bom", (sm - sl) * 1.3, "Bom controle de spray",
                f"Da 4ª à 7ª bala você acerta {sm:.0f}% ({label}: {sl:.0f}%).")
    x = d("hs")
    if x is not None:
        if x < -3:
            add("melhorar", abs(x) * 1.2, "Mira baixa",
                f"Só {me['hs']:.0f}% dos seus acertos são na cabeça ({label}: {lob['hs']:.0f}%).",
                "Ande com a mira na altura da cabeça, colada nos cantos onde o inimigo aparece (crosshair placement).")
        elif x > 3:
            add("bom", abs(x) * 1.2, "Mira na cabeça",
                f"{me['hs']:.0f}% dos seus acertos são na cabeça ({label}: {lob['hs']:.0f}%).")
    a, b = me.get("ajuste"), lob.get("ajuste")
    if a is not None and b:
        if a > b * 1.25 and a - b >= 1:
            add("melhorar", (a / b - 1) * 20, "Mira chega longe do inimigo",
                f"Antes do primeiro tiro você mexe a mira {a:.1f}° em média ({label}: {b:.1f}°). Precisa corrigir muito antes de atirar.",
                "Pré-mire os lugares onde o inimigo vai aparecer. Revise no replay onde estava sua mira antes dos duelos.")
        elif a < b * 0.8 and b - a >= 1:
            add("bom", (1 - a / b) * 20, "Mira já posicionada",
                f"Antes do primeiro tiro você mexe a mira só {a:.1f}° ({label}: {b:.1f}°). Bom posicionamento.")
    x = d("rajada_longa")
    if x is not None and x > 8:
        add("melhorar", x * 0.6, "Rajadas longas demais",
            f"{me['rajada_longa']:.0f}% das suas rajadas passam de 8 balas ({label}: {lob['rajada_longa']:.0f}%).",
            "Se errou as primeiras balas de longe, pare, reposicione a mira e atire de novo (burst).")
    if (me.get("no_ar") or 0) > 2 and (me.get("no_ar") or 0) > (lob.get("no_ar") or 0) * 1.5:
        add("melhorar", me["no_ar"], "Tiros no ar",
            f"{me['no_ar']:.1f}% dos seus tiros saem pulando ({label}: {lob.get('no_ar') or 0:.1f}%). Quase nunca acertam.")
    return sorted(out, key=lambda v: -v["peso"])


def stats(ids: list[int], me: str) -> dict:
    migrate()
    if not ids:
        return {"partidas": 0}
    marks = ",".join(str(int(i)) for i in ids)
    rows = db.q(f"""SELECT s.match_id, s.steamid, s.weapon, s.moving, s.air, s.burst, s.hit, s.head, s.flick, s.scoped,
                           s.strafe, s.strafe_ms
                    FROM demo_shots s WHERE s.match_id IN ({marks}) AND s.steamid != ''""")
    mine = [(r["weapon"], r["moving"], r["air"], r["burst"], r["hit"], r["head"], r["flick"], r["scoped"])
            for r in rows if r["steamid"] == me]
    lobby = [(r["weapon"], r["moving"], r["air"], r["burst"], r["hit"], r["head"], r["flick"], r["scoped"])
             for r in rows if r["steamid"] != me]
    if not mine:
        return {"partidas": len(ids), "tiros": 0}
    me_s, lob_s = _summary(mine), _summary(lobby)
    cs_me = _strafe_summary([(r["strafe"], r["strafe_ms"]) for r in rows if r["steamid"] == me])
    cs_lob = _strafe_summary([(r["strafe"], r["strafe_ms"]) for r in rows if r["steamid"] != me])

    # por arma
    kills = defaultdict(int)
    for k in db.q(f"SELECT weapon FROM demo_kills WHERE match_id IN ({marks}) AND attacker=?", me):
        kills[_w(k["weapon"])] += 1
    by_w = defaultdict(list)
    lob_w = defaultdict(list)
    for r in mine:
        by_w[r[0]].append(r)
    for r in lobby:
        lob_w[r[0]].append(r)
    armas = []
    for w, rs in sorted(by_w.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < 15:
            continue
        s = _summary(rs)
        ls = _summary(lob_w.get(w, [])) if lob_w.get(w) else {}
        armas.append({"arma": w, "nome": NAMES.get(w, w), "abates": kills.get(w, 0), **s,
                      "lobby": {k: ls.get(k) for k in ("precisao", "hs", "primeiro", "andando", "spray_meio")}})

    # curva do spray das armas automáticas que você mais usa
    top = [a["arma"] for a in armas if a["arma"] in SPRAY][:2]
    curvas = [{"arma": w, "nome": NAMES.get(w, w), "voce": _curve(mine, {w}), "lobby": _curve(lobby, {w})}
              for w in top]

    # evolução por partida (da mais antiga para a mais nova)
    order = {mid: i for i, mid in enumerate(ids)}
    per = defaultdict(list)
    for r in rows:
        if r["steamid"] == me:
            per[r["match_id"]].append((r["weapon"], r["moving"], r["air"], r["burst"], r["hit"], r["head"], r["flick"], r["scoped"]))
    info = {m["id"]: m for m in db.q(f"SELECT id, map, source, COALESCE(played_at, ended_at, started_at) quando FROM matches WHERE id IN ({marks})")}
    evolucao = []
    for mid in sorted(per, key=lambda m: -order[m]):
        s = _summary(per[mid])
        evolucao.append({"match_id": mid, "map": info[mid]["map"], "source": info[mid]["source"], "quando": info[mid]["quando"],
                         "precisao": s["precisao"], "andando": s["andando"], "hs": s["hs"], "tiros": s["tiros"]})
    per_cs = defaultdict(list)
    for r in rows:
        if r["steamid"] == me:
            per_cs[r["match_id"]].append((r["strafe"], r["strafe_ms"]))
    for e in evolucao:
        s = _strafe_summary(per_cs[e["match_id"]])
        e["cedo"] = s and s["cedo"]
        e["parou"] = s and s["ok_cs"] + s["ok_solto"]
    verdicts = sorted(_verdicts(me_s, lob_s) + _strafe_verdicts(cs_me, cs_lob), key=lambda v: -v["peso"])
    return {"partidas": len(ids), "voce": me_s, "lobby": lob_s, "veredito": verdicts,
            "strafe": {"voce": cs_me, "lobby": cs_lob} if cs_me else None,
            "armas": armas, "curvas": curvas, "evolucao": evolucao}


def mine(ids: list[int], me: str) -> dict | None:
    """Só os seus números (sem lobby): base "geral" para comparar com as últimas partidas."""
    if not ids:
        return None
    marks = ",".join(str(int(i)) for i in ids)
    rows = db.q(f"""SELECT weapon, moving, air, burst, hit, head, flick, scoped, strafe, strafe_ms FROM demo_shots
                    WHERE match_id IN ({marks}) AND steamid=?""", me)
    if not rows:
        return None
    return {"partidas": len(ids), "voce": _summary([tuple(r)[:8] for r in rows]),
            "strafe": _strafe_summary([(r["strafe"], r["strafe_ms"]) for r in rows])}


def match_line(match_id: int, me: str) -> str | None:
    """Resumo da mira numa partida, para o contexto das dicas do coach."""
    st = stats([match_id], me)
    v, lb = st.get("voce"), st.get("lobby")
    if not v:
        return None
    f = lambda x: "?" if x is None else f"{x:.0f}%"  # noqa: E731
    return (f"MIRA (você x média dos outros 9): precisão {f(v['precisao'])} x {f(lb['precisao'])}; "
            f"1ª bala {f(v['primeiro'])} x {f(lb['primeiro'])}; HS dos acertos {f(v['hs'])} x {f(lb['hs'])}; "
            f"tiros andando {f(v['andando'])} x {f(lb['andando'])} (andando você acerta {f(v['prec_andando'])}, parado {f(v['prec_parado'])}); "
            f"spray 4ª-7ª bala {f(v['spray_meio'])} x {f(lb['spray_meio'])}; "
            f"ajuste da mira antes do 1º tiro {v['ajuste'] if v['ajuste'] is not None else '?'}° x {lb['ajuste'] if lb['ajuste'] is not None else '?'}°")
