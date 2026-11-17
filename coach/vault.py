"""Configurações feitas pela interface.

- Chaves (segredos) ficam no Gerenciador de Credenciais do Windows (criptografado pelo Windows).
- O resto (nick, share code) fica no banco local.
A interface nunca recebe uma chave inteira, só os últimos 4 caracteres.
"""
from __future__ import annotations

import keyring

SERVICE = "CS2Coach"
SECRETS = {"faceit_key", "faceit_downloads_token", "steam_key", "steam_auth_code"}
PLAIN = {"faceit_nickname", "steam_last_sharecode"}


def get(name: str) -> str:
    if name in SECRETS:
        try:
            return keyring.get_password(SERVICE, name) or ""
        except Exception:
            return ""
    from . import db
    return db.kv_get(f"cfg_{name}") or ""


def set(name: str, value: str) -> None:  # noqa: A001
    value = (value or "").strip()
    if name in SECRETS:
        if value:
            keyring.set_password(SERVICE, name, value)
        else:
            try:
                keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        return
    if name in PLAIN:
        from . import db
        db.kv_set(f"cfg_{name}", value)
        return
    raise KeyError(name)


def mask(value: str) -> str:
    return f"••••{value[-4:]}" if len(value) > 6 else ("••••" if value else "")
