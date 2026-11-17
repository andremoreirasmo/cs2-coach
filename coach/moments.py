"""Destaques da partida e erros de economia. Tudo calculado das tabelas da análise, sem IA."""
from __future__ import annotations

from collections import defaultdict

from . import db

TICK = 64
WEAPON = {"ak47": "AK-47", "m4a1": "M4A4", "m4a1_silencer": "M4A1-S", "awp": "AWP", "deagle": "Desert Eagle",
          "usp_silencer": "USP-S", "glock": "Glock", "galilar": "Galil", "famas": "FAMAS", "ssg08": "Scout",
          "mp9": "MP9", "mac10": "MAC-10", "hkp2000": "P2000", "p250": "P250", "tec9": "Tec-9", "fiveseven": "Five-SeveN",
          "cz75a": "CZ75", "taser": "Zeus", "hegrenade": "HE", "inferno": "molotov", "elite": "Dual Berettas"}
BUY = {"pistol": "pistol", "eco": "eco", "forçado": "forçado", "forcado": "forçado", "completo": "completo"}


def _brl(n) -> str:
    """$1.412 (ponto de milhar, como no Brasil)."""
    return "$" + f"{round(n or 0):,}".replace(",", ".")


def _w(name) -> str:
    n = str(name or "").removeprefix("weapon_")
    if n.startswith("knife") or n == "bayonet":
        return "faca"
    return WEAPON.get(n, n)


def _half_ends(last: int) -> set[int]:
    """Últimos rounds de cada metade (o dinheiro zera depois deles)."""
    ends = {12, 24}
    r = 27
    while r <= last + 3:
        ends.add(r)
        r += 3
    return ends


def _base(mid: int):
    m = db.q1("SELECT id, my_steamid, rounds_total FROM matches WHERE id=?", mid)
    if not m:
        return None
    players = {p["steamid"]: dict(p) for p in db.q("SELECT steamid, name, team FROM demo_players WHERE match_id=?", mid)}
    rounds = {r["round_num"]: dict(r) for r in db.q("SELECT * FROM demo_rounds WHERE match_id=? ORDER BY round_num", mid)}
    return m, players, rounds


# ---------------------------------------------------------------- destaques
def highlights(mid: int) -> dict:
    base = _base(mid)
    if not base:
        return {"itens": []}
    m, players, rounds = base
    me = m["my_steamid"]
    name = lambda s: players.get(s, {}).get("name") or "?"  # noqa: E731
    kills = [dict(k) for k in db.q("SELECT * FROM demo_kills WHERE match_id=? ORDER BY tick", mid)]
    out = []

    def add(tipo, rn, tick, sid, titulo, detalhe, bom=True, peso=1):
        out.append({"tipo": tipo, "round": rn, "tick": int(tick or 0), "steamid": sid, "nome": name(sid),
                    "seu": sid == me, "titulo": titulo, "detalhe": detalhe, "bom": bom, "peso": peso})

    # vários abates no mesmo round
    per = defaultdict(list)
    for k in kills:
        a, v = k["attacker"], k["victim"]
        if a and a != v and players.get(a, {}).get("team") != players.get(v, {}).get("team"):
            per[(k["round_num"], a)].append(k)
    for (rn, sid), ks in per.items():
        n = len(ks)
        if n >= 3:
            secs = (ks[-1]["tick"] - ks[0]["tick"]) / TICK
            armas = ", ".join(sorted({_w(k["weapon"]) for k in ks}))
            hs = sum(1 for k in ks if k["headshot"])
            titulo = "ACE" if n >= 5 else f"{n} abates"
            add("multi", rn, ks[0]["tick"], sid, titulo,
                f"{n} abates em {secs:.0f} s com {armas}" + (f" · {hs} de headshot" if hs else ""), True, n * 2)

    # clutches (1 contra 2 ou mais, e 1v1 ganho)
    for c in db.q("SELECT * FROM demo_clutches WHERE match_id=?", mid):
        if c["vs"] < 2 and not c["won"]:
            continue
        sid = c["steamid"]
        if c["won"]:
            add("clutch", c["round_num"], c["tick"], sid, f"Clutch 1v{c['vs']} ganho",
                f"Sozinho contra {c['vs']}, com {c['kills']} abate(s)", True, 3 + c["vs"])
        elif sid == me:
            add("clutch", c["round_num"], c["tick"], sid, f"Clutch 1v{c['vs']} perdido",
                f"Ficou sozinho contra {c['vs']} e fez {c['kills']} abate(s)", False, 1)

    # seus abates especiais e suas primeiras mortes
    for k in kills:
        rn, a, v = k["round_num"], k["attacker"], k["victim"]
        if a == me and v != me:
            extra = []
            if k["thru_smoke"]:
                extra.append("através da smoke")
            if k["wallbang"]:
                extra.append("atravessando parede")
            if k["attacker_blind"]:
                extra.append("cego")
            w = _w(k["weapon"])
            if w in ("faca", "Zeus"):
                add("especial", rn, k["tick"], a, f"Abate de {w}", f"Em {name(v)}", True, 4)
            elif extra:
                add("especial", rn, k["tick"], a, "Abate " + " e ".join(extra), f"Em {name(v)} com {w}", True, 2)
            if k["first_kill"]:
                add("abertura", rn, k["tick"], a, "Abriu o round", f"Primeiro abate em {name(v)} com {w}", True, 1)
        elif v == me and k["first_kill"]:
            add("primeira_morte", rn, k["tick"], v, "Morreu primeiro", f"Para {name(a)} com {_w(k['weapon'])}"
                + (" · foi trocado" if k["traded"] else " · não foi trocado"), False, 1)

    # defuses e plants decisivos (o round foi ganho)
    for b in db.q("SELECT * FROM demo_bomb WHERE match_id=? AND kind='desarmou'", mid):
        add("bomba", b["round_num"], b["tick"], b["steamid"], "Desarmou a bomba", f"Bomb {b['site'] or ''}".strip(), True, 2)

    # eco ganho pelo seu time
    my_team = players.get(me, {}).get("team")
    if my_team:
        for rn, r in rounds.items():
            buy = r["buy_a"] if my_team == "A" else r["buy_b"]
            if buy == "eco" and r["winner_team"] == my_team:
                add("eco", rn, r["start_tick"], me, "Eco ganho", "Seu time venceu o round economizando", True, 3)

    # replay começa um pouco antes do lance
    for x in out:
        x["replay_tick"] = max(0, x["tick"] - 8 * TICK)
    out.sort(key=lambda x: (x["round"], x["tick"]))
    return {"itens": out, "me": me}


def best(ids: list[int], limit: int = 400) -> dict:
    """Suas melhores jogadas de várias partidas, das mais fortes para as mais fracas."""
    if not ids:
        return {"itens": [], "total": 0, "tipos": {}, "partidas": 0}
    info = {r["id"]: dict(r) for r in db.q(
        f"""SELECT id, map, source, result, my_score, enemy_score, COALESCE(played_at, ended_at, started_at) AS quando
            FROM matches WHERE id IN ({",".join(str(int(i)) for i in ids)})""")}
    out = []
    for mid in ids:
        m = info.get(mid, {})
        for x in highlights(mid)["itens"]:
            # eco ganho é do time, não uma jogada sua
            if x["seu"] and x["bom"] and x["tipo"] != "eco":
                out.append({**x, "match_id": mid, "mapa": m.get("map"), "fonte": m.get("source"),
                            "resultado": m.get("result"), "placar": f"{m.get('my_score')}:{m.get('enemy_score')}",
                            "quando": m.get("quando")})
    # mais forte primeiro; empate fica com a partida mais recente
    out.sort(key=lambda x: str(x["quando"] or ""), reverse=True)
    out.sort(key=lambda x: x["peso"], reverse=True)
    tipos = defaultdict(int)
    for x in out:
        tipos[x["tipo"]] += 1
    return {"itens": out[:limit], "total": len(out), "tipos": dict(tipos), "partidas": len(ids)}


# ---------------------------------------------------------------- economia
def economy(mid: int) -> dict:
    base = _base(mid)
    if not base:
        return {"rounds": [], "erros": []}
    m, players, rounds = base
    me = m["my_steamid"]
    my_team = players.get(me, {}).get("team")
    if not me or not my_team:
        return {"rounds": [], "erros": [], "sem_jogador": True}
    last = max(rounds) if rounds else 0
    ends = _half_ends(last)
    pr = defaultdict(dict)
    for r in db.q("SELECT round_num, steamid, side, equip, money, kills, deaths FROM demo_player_rounds WHERE match_id=?", mid):
        pr[r["round_num"]][r["steamid"]] = dict(r)
    mates = [s for s, p in players.items() if p["team"] == my_team and s != me]

    linhas, erros = [], []
    for rn in sorted(rounds):
        r = rounds[rn]
        mine = pr[rn].get(me)
        if not mine:
            continue
        equip, money = mine["equip"] or 0, mine["money"] or 0
        buy = BUY.get(r["buy_a"] if my_team == "A" else r["buy_b"], "?")
        enemy_buy = BUY.get(r["buy_b"] if my_team == "A" else r["buy_a"], "?")
        others = [pr[rn][s]["equip"] or 0 for s in mates if s in pr[rn]]
        team_avg = sum(others) / len(others) if others else 0
        won = r["winner_team"] == my_team
        nxt = rounds.get(rn + 1)
        nxt_buy = BUY.get((nxt["buy_a"] if my_team == "A" else nxt["buy_b"]), None) if nxt else None
        flags = []

        def err(tipo, titulo, texto, valor=0, time=False):
            flags.append(tipo)
            erros.append({"round": rn, "tipo": tipo, "titulo": titulo, "texto": texto, "valor": valor, "time": time,
                          "tick": r["start_tick"]})

        pistol = rn in (1, 13)
        # último round antes da troca de lado: o dinheiro zera. Só é erro se dava para usar em algo
        short = [(players[s]["name"], pr[rn][s]["equip"] or 0) for s in mates if s in pr[rn] and (pr[rn][s]["equip"] or 0) < 3000]
        if rn in ends and rn != last and money >= 800 and (equip < 4700 or (short and money >= 2700)):
            if equip < 4700:
                txt = (f"Último round antes da troca de lado: o dinheiro que sobra zera. Você entrou com {_brl(equip)} "
                       "de equipamento; dava para completar com granadas, colete ou kit.")
            else:
                quem = ", ".join(n for n, _ in short[:2])
                txt = (f"Último round antes da troca de lado: o dinheiro que sobra zera. Você já estava completo, "
                       f"mas dava para comprar uma arma para {quem}.")
            err("desperdicio", f"Sobrou {_brl(money)} sem usar", txt, money)
        elif not pistol and buy == "completo" and equip < 2700 and money >= 2000:
            err("comprou_menos", "Comprou menos do que podia",
                f"O time comprou completo (média de {_brl(team_avg)}) e você entrou com {_brl(equip)} tendo {_brl(money)} sobrando."
                , money)
        elif not pistol and team_avg < 1500 and equip >= 3000 and money < 3000 and others:
            err("fora_do_time", "Comprou sozinho",
                f"O time economizou (média de {_brl(team_avg)}) e você gastou: {_brl(equip)} de equipamento. "
                "Comprar fora de sincronia deixa os dois rounds seguintes mais fracos.", equip)
        elif not pistol and buy != "eco" and team_avg >= 3600 and equip < 2000 and money < 1500:
            flags.append("sem_dinheiro")  # não tinha como comprar: só informação

        # força do time que quebrou a economia
        if not pistol and buy == "forçado" and not won and nxt_buy == "eco" and rn not in ends:
            err("forca", "Força que quebrou a economia",
                "O time forçou, perdeu e teve que economizar no round seguinte. Às vezes é melhor economizar junto "
                "para comprar completo depois.", 0, True)

        linhas.append({"round": rn, "lado": mine["side"], "compra": buy, "compra_inimigo": enemy_buy, "equip": equip,
                       "sobrou": money, "media_time": round(team_avg), "ganhou": won, "abates": mine["kills"],
                       "morreu": bool(mine["deaths"]), "flags": flags, "tick": r["start_tick"]})

    # resumo
    def taxa(kind):
        rs = [x for x in linhas if x["compra"] == kind]
        return {"n": len(rs), "ganhos": sum(x["ganhou"] for x in rs)}
    resumo = {
        "desperdicado": sum(e["valor"] for e in erros if e["tipo"] == "desperdicio"),
        "erros_seus": sum(1 for e in erros if not e["time"]),
        "erros_time": sum(1 for e in erros if e["time"]),
        "por_compra": {k: taxa(k) for k in ("pistol", "eco", "forçado", "completo")},
    }
    return {"rounds": linhas, "erros": erros, "resumo": resumo}


def context_line(mid: int) -> str | None:
    """Erros de economia, para as dicas do coach."""
    e = economy(mid)
    if not e.get("erros"):
        return None
    parts = [f"R{x['round']} {x['titulo']}" + (" (time)" if x["time"] else "") for x in e["erros"]]
    return "ECONOMIA (erros detectados): " + "; ".join(parts)
