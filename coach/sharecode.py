"""Decodifica share codes (CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx) em matchid/outcomeid/token.

O matchid aparece no nome das demos baixadas pelo jogo (match730_<matchid>_...),
o que permite ligar a demo à partida certa.
"""
from __future__ import annotations

ALPHABET = "ABCDEFGHJKLMNOPQRSTUVWXYZabcdefhijkmnopqrstuvwxyz23456789"


def decode(code: str) -> dict:
    s = code.removeprefix("CSGO-").replace("-", "")
    if len(s) != 25:
        raise ValueError(f"share code inválido: {code}")
    n = 0
    for ch in reversed(s):
        n = n * len(ALPHABET) + ALPHABET.index(ch)
    b = n.to_bytes(18, "big")
    return {
        "match_id": int.from_bytes(b[0:8], "little"),
        "outcome_id": int.from_bytes(b[8:16], "little"),
        "token": int.from_bytes(b[16:18], "little"),
    }
