"""Rotas para adicionar demos à mão (botão "Adicionar demo") e abrir a sala da FACEIT."""
from __future__ import annotations

import re
import webbrowser
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, Request

from . import db, faceit
from .demos import EXTS, import_demo, signature
from .faceit import INBOX
from .settings_api import same_origin

FACEIT_ID = re.compile(r"^1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def make_router(pick_files: Callable[[], list[str]] | None, on_demo: Callable[[int], None]) -> APIRouter:
    r = APIRouter()

    def _import(path: Path, hint: int | None) -> dict:
        if not any(path.name.lower().endswith(e) for e in EXTS):
            return {"file": path.name, "ok": False, "msg": "não é uma demo do CS2 (.dem, .dem.gz, .dem.zst)"}
        old = db.q1("SELECT match_id FROM demos WHERE original=?", signature(path))
        if old:
            return {"file": path.name, "ok": True, "match_id": old["match_id"], "msg": "já estava importada"}
        mid = import_demo(path, hint_match_id=hint)
        if not mid:
            return {"file": path.name, "ok": False, "msg": "não consegui ler a demo (arquivo incompleto ou de outro jogo)"}
        on_demo(mid)
        return {"file": path.name, "ok": True, "match_id": mid, "msg": "importada, analisando…"}

    def _hint(request_json: dict) -> int | None:
        mid = request_json.get("match_id")
        return int(mid) if mid and db.q1("SELECT 1 FROM matches WHERE id=?", int(mid)) else None

    @r.post("/api/demos/pick")
    async def pick(request: Request):
        """Abre o seletor de arquivos do Windows e importa as demos escolhidas."""
        same_origin(request)
        if not pick_files:
            raise HTTPException(501, "seletor indisponível")
        hint = _hint(await request.json())
        paths = pick_files() or []
        from starlette.concurrency import run_in_threadpool  # importar 400 MB leva alguns segundos
        results = [await run_in_threadpool(_import, Path(p), hint) for p in paths]
        return {"results": results}

    @r.post("/api/demos/upload")
    async def upload(request: Request):
        """Plano B fora da janela do app: recebe o arquivo pelo navegador."""
        same_origin(request)
        name = Path(request.headers.get("x-filename", "")).name
        if not any(name.lower().endswith(e) for e in EXTS):
            raise HTTPException(400, "envie um arquivo .dem, .dem.gz ou .dem.zst")
        hint = request.headers.get("x-match-id")
        dst = INBOX / name
        tmp = dst.with_name(dst.name + ".part")
        with open(tmp, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
        tmp.replace(dst)
        from starlette.concurrency import run_in_threadpool
        return {"results": [await run_in_threadpool(_import, dst, _hint({"match_id": hint}))]}

    @r.post("/api/open-faceit/{fid}")
    def open_room(fid: str, request: Request):
        same_origin(request)
        if not FACEIT_ID.match(fid):
            raise HTTPException(400)
        webbrowser.open(faceit.room_url(fid))
        return {"ok": True}

    return r
