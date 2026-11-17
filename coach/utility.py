"""Biblioteca das suas granadas por mapa: de onde você joga, onde cai e se funciona.

Os lugares (callouts) de lançamento e de queda vêm do ponto conhecido mais próximo: as
posições de abates gravadas nas demos desse mapa já têm o nome do lugar.
"""
from __future__ import annotations

import math
from collections import defaultdict

from . import db
from .callouts import br

TIPOS = ("smoke", "flash", "he", "molotov")


def _places(map_name: str, ids: list[int]) -> list[tuple[float, float, str]]:
    pts = {}
    for r in db.q(f"""SELECT ax x, ay y, att_place p FROM demo_kills WHERE match_id IN (
                        SELECT id FROM matches WHERE map=?) AND att_place IS NOT NULL AND ax IS NOT NULL
                      UNION ALL
                      SELECT vx, vy, vic_place FROM demo_kills WHERE match_id IN (
                        SELECT id FROM matches WHERE map=?) AND vic_place IS NOT NULL AND vx IS NOT NULL""",
                  map_name, map_name):
        pts[(round(r["x"] / 48), round(r["y"] / 48))] = (r["x"], r["y"], r["p"])
    return list(pts.values())


def _nearest(pts, x, y) -> str | None:
    if x is None or not pts:
        return None
    best, bd = None, 600.0 ** 2
    for px, py, name in pts:
        d = (px - x) ** 2 + (py - y) ** 2
        if d < bd:
            best, bd = name, d
    return best


def _good(g) -> bool:
    t = g["type"]
    if t == "flash":
        return g["enemies_blinded"] >= 1 and not g["mates_blinded"]
    if t == "he":
        return g["damage"] >= 25
    if t == "molotov":
        return g["damage"] >= 10
    return True


def library(map_name: str, ids: list[int], me: str | None, tipo: str | None = None, side: str | None = None) -> dict:
    if not ids:
        return {"grupos": [], "lances": []}
    marks = ",".join(str(int(i)) for i in ids)
    sql = f"""SELECT match_id, round_num, side, type, throw_tick, det_tick, tx, ty, x, y,
                     enemies_blinded, mates_blinded, blind_time, damage, hits
              FROM demo_grenades WHERE match_id IN ({marks}) AND x IS NOT NULL"""
    args = []
    if me:
        sql += " AND thrower=?"
        args.append(me)
    if tipo in TIPOS:
        sql += " AND type=?"
        args.append(tipo)
    if side in ("CT", "T"):
        sql += " AND side=?"
        args.append(side)
    rows = [dict(r) for r in db.q(sql, *args)]
    pts = _places(map_name, ids)
    groups = defaultdict(list)
    for g in rows:
        g["de"] = br(map_name, _nearest(pts, g["tx"], g["ty"])) or "?"
        g["para"] = br(map_name, _nearest(pts, g["x"], g["y"])) or "?"
        g["boa"] = _good(g)
        groups[(g["type"], g["side"], g["de"], g["para"])].append(g)

    # mesma origem e destino, mas pontos de queda diferentes (ex.: 3 smokes no Bomb A) viram itens separados
    clusters = []
    for key, gs in groups.items():
        cs: list[list[dict]] = []
        for g in sorted(gs, key=lambda g: g["throw_tick"]):
            for c in cs:
                cx, cy = sum(x["x"] for x in c) / len(c), sum(x["y"] for x in c) / len(c)
                if math.hypot(g["x"] - cx, g["y"] - cy) < 160:
                    c.append(g)
                    break
            else:
                cs.append([g])
        clusters += [(key, c) for c in cs]

    out = []
    for (t, s, de, para), gs in clusters:
        n = len(gs)
        cx, cy = sum(g["x"] for g in gs) / n, sum(g["y"] for g in gs) / n
        spread = sum(math.hypot(g["x"] - cx, g["y"] - cy) for g in gs) / n
        boas = sum(g["boa"] for g in gs)
        item = {"tipo": t, "lado": s, "de": de, "para": para, "n": n, "boas": boas,
                "espalhamento_m": round(spread / 39.37, 1), "x": round(cx), "y": round(cy),
                "tx": round(sum(g["tx"] for g in gs) / n), "ty": round(sum(g["ty"] for g in gs) / n)}
        if t == "flash":
            item["cegou"] = round(sum(g["enemies_blinded"] for g in gs) / n, 1)
            item["cegou_aliado"] = round(sum(g["mates_blinded"] for g in gs) / n, 1)
            item["tempo_cego"] = round(sum(g["blind_time"] for g in gs) / n, 1)
        if t in ("he", "molotov"):
            item["dano"] = round(sum(g["damage"] for g in gs) / n)
        # smoke e molotov: o que importa é cair sempre no mesmo lugar (molotov muitas vezes é só para segurar)
        if t in ("smoke", "molotov"):
            item["nota"] = "repete" if n >= 2 and spread < 120 else ("varia" if n >= 2 else "uma vez")
        else:
            r = boas / n
            item["nota"] = "boa" if r >= 0.6 else ("as_vezes" if r >= 0.3 else "ruim")
        item["exemplos"] = [{"match_id": g["match_id"], "round_num": g["round_num"], "tick": g["throw_tick"],
                             "boa": g["boa"]} for g in sorted(gs, key=lambda g: (-g["boa"], -g["match_id"]))[:6]]
        out.append(item)
    out.sort(key=lambda i: (-i["n"], i["tipo"]))
    lances = [{"tipo": g["type"], "tx": g["tx"], "ty": g["ty"], "x": g["x"], "y": g["y"], "boa": g["boa"],
               "de": g["de"], "para": g["para"]} for g in rows]
    resumo = {}
    for t in TIPOS:
        gs = [g for g in rows if g["type"] == t]
        if gs:
            resumo[t] = {"n": len(gs), "boas": sum(g["boa"] for g in gs)}
    return {"grupos": out, "lances": lances, "resumo": resumo}
