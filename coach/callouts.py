"""Nomes de lugares como o pessoal fala no Brasil.

O jogo grava o lugar de cada jogador com o nome interno em inglês ("ShortStairs", "BombsiteB").
Aqui eles viram o callout usado nos servidores brasileiros. Para corrigir ou trocar um nome,
é só editar a tabela do mapa.
"""
from __future__ import annotations

import re

COMMON = {
    "BombsiteA": "Bomb A", "BombsiteB": "Bomb B", "CTSpawn": "Base CT", "TSpawn": "Base TR",
    "Middle": "Meio", "TopofMid": "Topo do meio", "TRamp": "Rampa TR", "BackAlley": "Beco",
}

MAPS = {
    "de_dust2": {
        "LongA": "Long", "OutsideLong": "Fora do long", "LongDoors": "Portas do long", "Pit": "Buraco do long",
        "Side": "Lateral do buraco", "ARamp": "Rampa do A", "ExtendedA": "Frente do A", "UnderA": "Embaixo do A",
        "Catwalk": "Short", "ShortStairs": "Escada do short", "MidDoors": "Portas do meio", "Hole": "Buraco do túnel",
        "UpperTunnel": "Túnel de cima", "LowerTunnel": "Túnel de baixo", "TunnelStairs": "Escada do túnel",
        "BDoors": "Porta do B", "Middle": "Meio", "TopofMid": "Topo do meio",
    },
    "de_inferno": {
        "Banana": "Banana", "Apartments": "Apto", "Balcony": "Varanda", "Arch": "Arco", "Library": "Biblioteca",
        "Pit": "Poço", "Quad": "Quadrado", "Ruins": "Ruínas", "Kitchen": "Cozinha", "Deck": "Deck",
        "Bridge": "Ponte", "Underpass": "Embaixo da ponte", "SecondMid": "Segundo meio", "Upstairs": "Escada do apto",
        "LowerMid": "Meio de baixo", "Graveyard": "Cemitério", "Construction": "Construção", "CTSpawn": "Base CT",
        "Coffins": "Caixão", "Boiler": "Fornalha", "Moto": "Moto",
    },
    "de_mirage": {
        "PalaceInterior": "Palácio", "PalaceAlley": "Beco do palácio", "Apartments": "Apto", "Shop": "Mercado",
        "SnipersNest": "Janela", "Connector": "Conector", "Jungle": "Jungle", "Catwalk": "Short", "Stairs": "Escada",
        "Underpass": "Esgoto", "Truck": "Caminhão", "House": "Casa", "Scaffolding": "Andaime", "Ladder": "Escada do CT",
        "SideAlley": "Beco lateral", "Ticket": "Bilheteria", "Tetris": "Tetris", "Firebox": "Firebox",
        "Market": "Mercado", "Kitchen": "Cozinha", "Bench": "Banco", "Tunnel": "Túnel",
    },
    "de_nuke": {
        "Outside": "Fora", "Ramp": "Rampa", "Mini": "Mini", "Lobby": "Lobby", "Rafters": "Vigas", "Squeaky": "Porta do squeaky",
        "Control": "Controle", "Tunnels": "Túneis", "Heaven": "Heaven", "Hell": "Hell", "Vending": "Máquina",
        "Hut": "Casinha", "HutRoof": "Teto da casinha", "Trophy": "Troféu", "Catwalk": "Passarela", "Admin": "Admin",
        "Silo": "Silo", "Roof": "Teto", "Secret": "Secreta", "Garage": "Garagem", "Vents": "Duto",
        "Observation": "Observação", "Decon": "Decon", "Crane": "Guindaste", "BombsiteA": "Bomb A (cima)",
        "BombsiteB": "Bomb B (baixo)",
    },
    "de_ancient": {
        "Donut": "Donut", "Cave": "Caverna", "Temple": "Templo", "Ramp": "Rampa", "Main": "Main",
    },
    "de_anubis": {
        "Canal": "Canal", "Bridge": "Ponte", "Palace": "Palácio", "Street": "Rua", "Walkway": "Passarela",
    },
}

# palavras comuns para os lugares que não estão nas tabelas
WORDS = {
    "Bombsite": "Bomb", "Spawn": "Base", "Stairs": "escada", "Upper": "de cima", "Lower": "de baixo",
    "Tunnel": "túnel", "Tunnels": "túneis", "Doors": "portas", "Door": "porta", "Ramp": "rampa", "Alley": "beco",
    "Long": "long", "Short": "short", "Mid": "meio", "Middle": "meio", "Window": "janela", "Bridge": "ponte",
    "Hall": "corredor", "Room": "sala", "Back": "fundo", "Side": "lateral", "Top": "topo", "Under": "embaixo",
    "Outside": "fora", "Inside": "dentro", "Garage": "garagem", "House": "casa", "Roof": "teto",
}


def br(map_name: str | None, place: str | None) -> str | None:
    """Nome do lugar em português (callout brasileiro)."""
    if not place:
        return place
    table = MAPS.get(map_name or "", {})
    if place in table:
        return table[place]
    if place in COMMON:
        return COMMON[place]
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", place)
    if not words:
        return place
    # "Upper Park" -> "Park de cima": em português o "de cima / de baixo" vem depois
    after = [w for w in words if w in ("Upper", "Lower")]
    words = [w for w in words if w not in ("Upper", "Lower")] + after
    s = " ".join(WORDS.get(w, w) for w in words)
    return s[0].upper() + s[1:]
