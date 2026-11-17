"""Configuração central: caminhos, chaves (.env) e localização do CS2."""
from __future__ import annotations

import os
import re
import secrets
import winreg
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEMOS = DATA / "demos"          # cópias descompactadas das demos (originais nunca são alteradas)
LOGS = DATA / "logs"
DB_PATH = DATA / "coach.db"
TOKEN_FILE = DATA / "gsi_token.txt"

for p in (DATA, DEMOS, LOGS):
    p.mkdir(parents=True, exist_ok=True)

load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def steam_path() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return Path(winreg.QueryValueEx(k, "SteamPath")[0])
    except OSError:
        return None


def find_cs2_dir() -> Path | None:
    """Procura a pasta do CS2 em todas as bibliotecas da Steam."""
    sp = steam_path()
    if not sp:
        return None
    libs = [sp]
    vdf = sp / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    for lib in libs:
        d = lib / "steamapps" / "common" / "Counter-Strike Global Offensive"
        if (d / "game" / "csgo").exists():
            return d
    return None


def gsi_token() -> str:
    """Token aleatório que o CS2 envia em cada mensagem; rejeitamos qualquer outra origem."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    tok = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(tok)
    return tok


def _cfg(name: str, env: str):
    """Valor salvo pela tela Configurações; o .env só serve de reserva."""
    def get(self) -> str:
        from . import vault
        return vault.get(name) or _env(env)
    return property(get)


@dataclass
class Settings:
    faceit_key = _cfg("faceit_key", "FACEIT_API_KEY")
    faceit_nickname = _cfg("faceit_nickname", "FACEIT_NICKNAME")
    faceit_downloads_token = _cfg("faceit_downloads_token", "FACEIT_DOWNLOADS_TOKEN")
    steam_key = _cfg("steam_key", "STEAM_WEB_API_KEY")
    steam_auth_code = _cfg("steam_auth_code", "STEAM_AUTH_CODE")
    steam_last_sharecode = _cfg("steam_last_sharecode", "STEAM_LAST_SHARECODE")

    @property
    def steam_id64(self) -> str:
        from . import db
        return db.kv_get("steamid") or _env("STEAM_ID64")

    gsi_port: int = field(default_factory=lambda: int(_env("GSI_PORT", "31982") or 31982))
    # GSI desligado por padrão: no seu PC ele deixou as animações do CS lentas.
    gsi_enabled: bool = field(default_factory=lambda: _env("GSI_ENABLED", "0") == "1")
    extra_demo_dirs: list[Path] = field(
        default_factory=lambda: [Path(p) for p in _env("EXTRA_DEMO_DIRS").split(";") if p.strip()]
    )

    @property
    def cs2_dir(self) -> Path | None:
        return find_cs2_dir()

    def demo_dirs(self) -> list[Path]:
        """Pastas onde aparecem demos: as do jogo, Downloads (FACEIT manual) e extras."""
        dirs: list[Path] = []
        cs = self.cs2_dir
        if cs:
            dirs += [cs / "game" / "csgo", cs / "game" / "csgo" / "replays"]
        dirs.append(Path.home() / "Downloads")
        dirs.append(DATA / "inbox")   # demos baixadas pela FACEIT Downloads API ou colocadas à mão
        dirs += self.extra_demo_dirs
        return dirs


settings = Settings()
