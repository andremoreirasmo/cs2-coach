"""Gera mensagens GSI de uma partida falsa (13x9 em de_mirage).

Uso:
  python -m tools.simulate_gsi            -> envia para o servidor rodando (teste ponta a ponta)
  (os testes em tests/ usam payloads() diretamente)
"""
from __future__ import annotations

import random
import sys

ME = "76561198000000001"
MATE = "76561198000000002"


def payloads(token: str, seed: int = 7, rounds_result: str = "CCCTCCTCCTCT" "TCCTCCCCTC"):
    """rounds_result: quem venceu cada round do ponto de vista dos lados (C=CT, T=TR)."""
    rnd = random.Random(seed)
    ct = t = 0
    wins: dict[str, str] = {}
    kills = deaths = 0

    def base(phase, rphase, player, extra_round=None):
        r = {"phase": rphase}
        if extra_round:
            r.update(extra_round)
        return {
            "provider": {"name": "Counter-Strike 2", "appid": 730, "steamid": ME},
            "map": {"mode": "competitive", "name": "de_mirage", "phase": phase, "round": ct + t,
                    "team_ct": {"score": ct}, "team_t": {"score": t}, "round_wins": dict(wins)},
            "round": r,
            "player": player,
            "auth": {"token": token},
        }

    def me(team, health=100, rk=0, rhs=0, dmg=0, money=800):
        return {"steamid": ME, "name": "eu", "team": team,
                "state": {"health": health, "armor": 100, "money": money, "round_kills": rk,
                          "round_killhs": rhs, "round_totaldmg": dmg, "equip_value": 4700},
                "match_stats": {"kills": kills, "assists": 2, "deaths": deaths, "mvps": 1, "score": kills * 2}}

    yield {"provider": {"steamid": ME}, "auth": {"token": token}}  # menu
    yield base("warmup", None, me("CT"))
    for i, w in enumerate(rounds_result):
        team = "CT" if i < 12 else "T"
        yield base("live", "freezetime", me(team, money=4000))
        yield base("live", "live", me(team))
        rk = rnd.randint(0, 3)
        rhs = rnd.randint(0, rk)
        dmg = rk * 100 + rnd.randint(0, 60)
        kills += rk
        died = rnd.random() < 0.5
        yield base("live", "live", me(team, rk=rk, rhs=rhs, dmg=dmg))
        if died:
            deaths += 1
            yield base("live", "live", me(team, health=0, rk=rk, rhs=rhs, dmg=dmg))
            yield base("live", "live", {"steamid": MATE, "team": team, "state": {"health": 50}})
        winner = "CT" if w == "C" else "T"
        if winner == "CT":
            ct += 1
        else:
            t += 1
        wins[str(ct + t)] = "ct_win_elimination" if winner == "CT" else "t_win_bomb"
        pl = {"steamid": MATE, "team": team, "state": {"health": 50}} if died else me(team, rk=rk, rhs=rhs, dmg=dmg)
        last = i == len(rounds_result) - 1
        yield base("gameover" if last else "live", "over", pl, {"win_team": winner})
    yield base("gameover", "over", me("T"))


def main() -> None:
    import httpx

    from coach.config import gsi_token, settings
    url = f"http://127.0.0.1:{settings.gsi_port}/gsi"
    n = 0
    with httpx.Client() as c:
        for p in payloads(gsi_token()):
            c.post(url, json=p).raise_for_status()
            n += 1
    print(f"{n} mensagens enviadas para {url}")
    sys.exit(0)


if __name__ == "__main__":
    main()
