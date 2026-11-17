"""Rotas da tela Configurações: salvar/testar chaves, abrir links, iniciar com o Windows."""
from __future__ import annotations

import re
import webbrowser

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import db, demos, services, vault
from .config import settings
from .sharecode import decode

router = APIRouter()

# links que a interface pode abrir no navegador (nada além disso)
LINKS = {
    "faceit_dev": "https://developers.faceit.com/",
    "faceit_downloads": "https://docs.faceit.com/getting-started/Guides/download-api",
    "steam_apikey": "https://steamcommunity.com/dev/apikey",
    "steam_authcode": "https://help.steampowered.com/pt-br/wizard/HelpWithGameIssue/?appid=730&issueid=128",
}
NICK = re.compile(r"[A-Za-z0-9_\-]{2,32}")


def same_origin(request: Request) -> None:
    """Só aceita mudanças vindas da própria janela do app (bloqueia sites tentando mexer aqui)."""
    origin = request.headers.get("origin")
    host = f"http://127.0.0.1:{settings.gsi_port}"
    if origin and origin not in (host, f"http://localhost:{settings.gsi_port}", "http://localhost:5173"):
        raise HTTPException(403, "origem não permitida")
    if request.headers.get("x-coach") != "1":
        raise HTTPException(403, "cabeçalho ausente")


def _status() -> dict:
    s = settings
    return {
        "faceit": {"key": vault.mask(s.faceit_key), "nickname": s.faceit_nickname,
                   "downloads": vault.mask(s.faceit_downloads_token),
                   "ok": bool(s.faceit_nickname), "auto": bool(s.faceit_key and s.faceit_nickname)},
        "steam": {"key": vault.mask(s.steam_key), "auth": vault.mask(s.steam_auth_code),
                  "sharecode": db.kv_get("steam_last_sharecode") or s.steam_last_sharecode,
                  "steamid": s.steam_id64,
                  "ok": bool(s.steam_key and s.steam_auth_code and s.steam_id64)},
        "app": {"pausar_no_jogo": services.pause_in_game(), "apagar_originais": demos.delete_originals_on(),
                "originais": demos.originals_left()},
    }


@router.get("/api/settings")
def get_settings():
    return _status()


# ---------------- testes das chaves ----------------
def _test_faceit(key: str, nick: str) -> tuple[str | None, str | None]:
    r = httpx.get("https://open.faceit.com/data/v4/players", params={"nickname": nick}, timeout=15,
                  headers={"Authorization": f"Bearer {key}"})
    if r.status_code == 401:
        return "Chave inválida. Use a chave do tipo Server side.", None
    if r.status_code == 404:
        return f'Nick "{nick}" não encontrado na FACEIT (maiúsculas e minúsculas contam).', None
    if r.status_code >= 400:
        return f"A FACEIT respondeu {r.status_code}.", None
    return None, r.json().get("player_id")


def _test_steam(key: str, auth: str, code: str, steamid: str) -> str | None:
    r = httpx.get("https://api.steampowered.com/ICSGOPlayers_730/GetNextMatchSharingCode/v1", timeout=15,
                  params={"key": key, "steamid": steamid, "steamidkey": auth, "knowncode": code})
    if r.status_code in (200, 202):
        return None
    if r.status_code == 403:
        return "Chave da Steam Web API inválida."
    if r.status_code == 412:
        return "Código de autenticação ou share code não conferem com a sua conta."
    return f"A Steam respondeu {r.status_code}."


# ---------------- salvar ----------------
@router.post("/api/settings/faceit")
async def save_faceit(request: Request):
    same_origin(request)
    body = await request.json()
    key = body.get("key", "").strip() or settings.faceit_key
    nick = body.get("nickname", "").strip()
    if body.get("clear"):
        vault.set("faceit_key", "")
        vault.set("faceit_nickname", "")
        db.kv_set("faceit_player_id", "")
        return _status()
    if not nick or not NICK.fullmatch(nick):
        raise HTTPException(400, "Escreva seu nick da FACEIT (só letras, números, - e _).")
    if not key:  # sem chave: só o nick, para abrir o histórico de partidas
        vault.set("faceit_nickname", nick)
        return _status()
    err, pid = _test_faceit(key, nick)
    if err:
        raise HTTPException(400, err)
    vault.set("faceit_key", key)
    vault.set("faceit_nickname", nick)
    db.kv_set("faceit_player_id", pid or "")
    if "downloads" in body:
        vault.set("faceit_downloads_token", body["downloads"])
    return _status()


@router.post("/api/settings/steam")
async def save_steam(request: Request):
    same_origin(request)
    body = await request.json()
    if body.get("clear"):
        for k in ("steam_key", "steam_auth_code"):
            vault.set(k, "")
        return _status()
    key = body.get("key", "").strip() or settings.steam_key
    auth = body.get("auth", "").strip() or settings.steam_auth_code
    code = body.get("sharecode", "").strip() or (db.kv_get("steam_last_sharecode") or settings.steam_last_sharecode)
    steamid = settings.steam_id64
    if not (key and auth and code):
        raise HTTPException(400, "Preencha a chave, o código de autenticação e o share code.")
    if not steamid:
        raise HTTPException(400, "Abra uma partida e escolha qual jogador é você (o app precisa do seu SteamID).")
    try:
        decode(code)
    except Exception:
        raise HTTPException(400, "Share code inválido. Formato: CSGO-xxxxx-xxxxx-xxxxx-xxxxx-xxxxx")
    auth = auth.upper() if "-" in auth else auth
    err = _test_steam(key, auth, code, steamid)
    if err:
        raise HTTPException(400, err)
    vault.set("steam_key", key)
    vault.set("steam_auth_code", auth)
    vault.set("steam_last_sharecode", code)
    db.kv_set("steam_last_sharecode", code)
    return _status()


# ---------------- outros ----------------
@router.post("/api/open/{name}")
def open_link(name: str, request: Request):
    same_origin(request)
    url = LINKS.get(name)
    if not url:
        raise HTTPException(404)
    webbrowser.open(url)
    return {"ok": True}


@router.post("/api/open-faceit-history")
def open_faceit_history(request: Request):
    """Abre a página de partidas do jogador na FACEIT (de lá, 'Assistir demo' baixa o arquivo)."""
    same_origin(request)
    nick = settings.faceit_nickname
    if not nick or not NICK.fullmatch(nick):
        raise HTTPException(400, "Configure seu nick da FACEIT.")
    webbrowser.open(f"https://www.faceit.com/pt/players/{nick}/stats/cs2")
    return {"ok": True}


@router.post("/api/settings/pausar")
async def set_pause(request: Request):
    same_origin(request)
    services.set_pause_in_game(bool((await request.json()).get("on")))
    return _status()


@router.post("/api/settings/originais")
async def set_originals(request: Request):
    same_origin(request)
    demos.set_delete_originals(bool((await request.json()).get("on")))
    return _status()


@router.post("/api/settings/originais/limpar")
def clean_originals(request: Request):
    same_origin(request)
    r = demos.delete_imported_originals()
    return {**_status(), "limpou": r}

