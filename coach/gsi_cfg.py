"""Cria o gamestate_integration_coach.cfg na pasta cfg do CS2.

Pedimos só os dados que o próprio jogo oferece ao jogador (os seus). Os blocos
"allplayers_*", "allgrenades" e posições ficam desligados: o CS2 só os envia para
espectadores/GOTV, e não precisamos deles — a análise completa vem da demo depois.
"""
from __future__ import annotations

from pathlib import Path

from .config import gsi_token, settings

CFG_NAME = "gamestate_integration_coach.cfg"


def cfg_text(port: int, token: str) -> str:
    return f'''"CS2 Coach (analise pos-partida)"
{{
  "uri"       "http://127.0.0.1:{port}/gsi"
  "timeout"   "5.0"
  "buffer"    "0.5"
  "throttle"  "0.5"
  "heartbeat" "30.0"
  "auth"
  {{
    "token" "{token}"
  }}
  "data"
  {{
    "provider"            "1"
    "map"                 "1"
    "map_round_wins"      "1"
    "round"               "1"
    "player_id"           "1"
    "player_state"        "1"
    "player_match_stats"  "1"
  }}
}}
'''


def cfg_path() -> Path | None:
    cs = settings.cs2_dir
    return cs / "game" / "csgo" / "cfg" / CFG_NAME if cs else None


def install() -> Path | None:
    path = cfg_path()
    if not path:
        raise SystemExit("Não encontrei a pasta do CS2. Verifique se a Steam e o CS2 estão instalados.")
    if not settings.gsi_enabled:  # desligado: garante que o CS não carregue nosso arquivo
        if path.exists():
            path.replace(path.with_name(path.name + ".off"))
        return None
    off = path.with_name(path.name + ".off")
    if off.exists():  # desativado por você: não recria
        return off
    text = cfg_text(settings.gsi_port, gsi_token())
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


if __name__ == "__main__":
    print("Arquivo GSI instalado em:", install())
    print("Reinicie o CS2 se ele estiver aberto.")
