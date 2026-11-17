"""Como cada morte aconteceu, medido na demo (sem IA).

No 1º dano que o matador deu: sua velocidade, a dele e para onde você mirava em relação a ele.
Daí sai o tipo do duelo: você entrou no ângulo dele, ele te pegou no peek, duelo de mira parado,
os dois em movimento, ou você foi pego de lado / de costas."""
from __future__ import annotations

from collections import Counter

from . import db
from .callouts import br
from .moments import _w

RUN = 100     # unidades/s: correndo (AK anda a 215; só fica precisa abaixo de ~70)
MOVE = 60     # você se mexendo o bastante para errar o 1º tiro
HOLD = 70     # média do matador no 0,5 s antes: abaixo disso ele segurava o ângulo; acima, veio no peek
SIDE, BACK = 45, 100  # graus entre sua mira e o matador

TIPOS = {
    "entrou": ("Entrou no ângulo dele", "Você se mexendo e ele parado, com a mira pronta. Pare antes do duelo ou use granada para tirar o ângulo."),
    "correndo": ("Correndo no duelo", "Você estava correndo quando ele te acertou. Mesmo com ele se mexendo, correndo você não acerta: pare antes de atirar."),
    "peek": ("Peek dele", "Ele veio para cima de você parado. Muitas vezes é duelo justo: veja se sua mira estava na altura certa."),
    "mira": ("Duelo de mira", "Os dois parados e de frente: ganhou quem mirou e atirou primeiro."),
    "movimento": ("Os dois se mexendo", "Encontro com os dois andando. Quem para primeiro costuma ganhar."),
    "lado": ("Pego de lado", "Ele apareceu fora de onde você mirava. Limpe um ângulo de cada vez e use o radar e o som."),
    "costas": ("Pego de costas", "Ele te acertou por trás. Comum em rotação ou depois de abate: confira o flanco."),
}
ORDEM = ["entrou", "correndo", "peek", "mira", "movimento", "lado", "costas"]


def tipo(vs: int | None, as_: int | None, ang: int | None) -> str | None:
    if vs is None or as_ is None or ang is None:
        return None
    if ang > BACK:
        return "costas"
    if ang > SIDE:
        return "lado"
    if vs < MOVE:
        return "mira" if as_ < HOLD else "peek"
    if as_ < HOLD:
        return "entrou"
    return "correndo" if vs >= RUN else "movimento"


def _in(ids) -> str:
    return ",".join(str(int(i)) for i in ids) or "NULL"


def match(mid: int) -> dict:
    """Suas mortes nesta partida, uma a uma, mais quem te matou mais e o resumo por tipo."""
    m = db.q1("SELECT map, my_steamid FROM matches WHERE id=?", mid)
    me = m and m["my_steamid"]
    if not me:
        return {"sem_jogador": True, "mortes": []}
    names = {r["steamid"]: r["name"] for r in db.q("SELECT steamid, name FROM demo_players WHERE match_id=?", mid)}
    rows = db.q("""SELECT * FROM demo_kills WHERE match_id=? AND victim=? AND attacker IS NOT NULL AND attacker!=''
                   AND attacker!=victim ORDER BY tick""", mid, me)
    mortes = []
    for i, k in enumerate(rows, 1):
        t = tipo(k["vic_speed"], k["att_speed"], k["vic_angle"])
        mortes.append({
            "n": i, "round": k["round_num"], "tick": k["tick"], "lado": k["victim_side"],
            "matador": names.get(k["attacker"], "?"), "arma": _w(k["weapon"]), "hs": bool(k["headshot"]),
            "onde": br(m["map"], k["vic_place"]), "de_onde": br(m["map"], k["att_place"]),
            "dist": round(k["att_dist"] / 39.37) if k["att_dist"] else None,
            "sua_vel": k["vic_speed"], "vel_dele": k["att_speed"], "angulo": k["vic_angle"], "tipo": t,
            "trocada": bool(k["traded"]), "primeira": bool(k["first_kill"]),
            "aliado": round(k["mate_dist"] / 39.37) if k["mate_dist"] else None,
            "vivos": [k["mates_alive"], k["enemies_alive"]],
            "na_mao": k["vic_weapon"], "granadas": k["vic_nades"],
        })
    killers = Counter(x["matador"] for x in mortes)
    spots = Counter((x["matador"], x["de_onde"]) for x in mortes if x["de_onde"])
    top = [{"nome": n, "n": c, "de_onde": [p for (k, p), _ in spots.most_common() if k == n][:2]}
           for n, c in killers.most_common(3) if c >= 2]
    return {"mortes": mortes, "resumo": _dist([x["tipo"] for x in mortes]), "matadores": top,
            "tipos": {k: {"titulo": a, "dica": b} for k, (a, b) in TIPOS.items()}, "ordem": ORDEM,
            "lobby": _dist(_types(f"SELECT vic_speed, att_speed, vic_angle FROM demo_kills WHERE match_id={int(mid)} AND victim!=?", me))}


def _types(sql: str, *args) -> list[str | None]:
    return [tipo(r["vic_speed"], r["att_speed"], r["vic_angle"]) for r in db.q(sql, *args)]


def _dist(ts: list[str | None]) -> dict:
    ts = [t for t in ts if t]
    n = len(ts)
    c = Counter(ts)
    return {"n": n, **{k: round(100 * c[k] / n) if n else 0 for k in ORDEM}}


def summary(ids: list[int], me: str) -> dict | None:
    """Tipos de morte: você x lobby (os outros nas suas partidas) e a tendência por partida."""
    if not ids:
        return None
    voce = _types(f"SELECT vic_speed, att_speed, vic_angle FROM demo_kills WHERE victim=? AND match_id IN ({_in(ids)})", me)
    if not any(voce):
        return None
    lobby = _types(f"SELECT vic_speed, att_speed, vic_angle FROM demo_kills WHERE victim!=? AND match_id IN ({_in(ids)})", me)
    trend = []
    for r in db.q(f"""SELECT m.id, m.map, COALESCE(m.played_at, m.ended_at) quando FROM matches m
                      WHERE m.id IN ({_in(ids)}) ORDER BY COALESCE(m.played_at, m.ended_at, m.started_at)"""):
        d = _dist(_types("SELECT vic_speed, att_speed, vic_angle FROM demo_kills WHERE victim=? AND match_id=?", me, r["id"]))
        if d["n"]:
            trend.append({"id": r["id"], "map": r["map"], "quando": r["quando"], **d})
    return {"voce": _dist(voce), "lobby": _dist(lobby), "tendencia": trend, "ordem": ORDEM, "tipos": {k: {"titulo": a, "dica": b} for k, (a, b) in TIPOS.items()}}
