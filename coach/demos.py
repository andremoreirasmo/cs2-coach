"""Monitor de demos (plano B) e importação de qualquer demo nova.

- Só LÊ as pastas do jogo/Downloads e nunca altera os originais.
- Copia/descompacta para data/demos e liga a demo à partida certa.
- Se a opção estiver ligada (Configurações), apaga o arquivo original depois que a cópia foi conferida,
  para não ocupar espaço duas vezes. Só apaga a própria demo importada, nada mais.
- Não processa nada enquanto você está em partida (não rouba CPU/disco do jogo).
"""
from __future__ import annotations

import bz2
import gzip
import hashlib
import logging
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

import zstandard

from . import db
from .config import DEMOS, settings

log = logging.getLogger("coach.demos")

EXTS = (".dem", ".dem.gz", ".dem.zst", ".dem.bz2")
STABLE_SECS = 20            # arquivo precisa ficar sem mudar esse tempo (download/gravação terminou)
LINK_WINDOW = 48 * 3600     # demo pode chegar até 48h depois da partida
MATCH730 = re.compile(r"match730_0*(\d+)_")
FACEIT_ID = re.compile(r"(1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def _is_demo(p: Path) -> bool:
    n = p.name.lower()
    return any(n.endswith(e) for e in EXTS)


def _copy_decompressed(src: Path, dst: Path) -> None:
    n = src.name.lower()
    tmp = dst.with_suffix(".part")
    if n.endswith(".gz"):
        opener = gzip.open(src, "rb")
    elif n.endswith(".bz2"):
        opener = bz2.open(src, "rb")
    elif n.endswith(".zst"):
        opener = zstandard.ZstdDecompressor().stream_reader(open(src, "rb"))
    else:
        opener = open(src, "rb")
    with opener as fin, open(tmp, "wb") as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)
    tmp.replace(dst)


def read_header(path: Path) -> dict:
    with open(path, "rb") as f:
        if f.read(8) != b"PBDEMS2\x00":
            raise ValueError("não é uma demo do CS2")
    from demoparser2 import DemoParser
    return DemoParser(str(path)).parse_header()


def source_from_header(h: dict) -> str:
    s = f"{h.get('server_name', '')} {h.get('demo_version_name', '')}".lower()
    if "faceit" in s:
        return "faceit"
    if "valve" in s:
        return "valve"
    return "desconhecido"


def signature(src: Path) -> str:
    st = src.stat()
    return f"{src.resolve()}|{st.st_size}|{int(st.st_mtime)}"


def _hint_ok(mid: int, map_name: str | None, fid: str | None) -> bool:
    """A partida sugerida só vale se combinar com a demo (mapa e id da FACEIT) e ainda não tiver demo."""
    m = db.q1("SELECT map, faceit_match_id, demo_id FROM matches WHERE id=?", mid)
    if not m or m["demo_id"]:
        return False
    if m["map"] and map_name and m["map"] != map_name:
        return False
    return not (fid and m["faceit_match_id"] and m["faceit_match_id"] != fid)


def import_demo(src: Path, hint_match_id: int | None = None) -> int | None:
    """Importa uma demo e devolve o id da partida vinculada."""
    try:
        st = src.stat()
    except OSError:  # o arquivo sumiu (apagado ou movido) antes de importar
        return None
    sig = signature(src)
    old = db.q1("SELECT id, match_id, status FROM demos WHERE original=?", sig)
    if old and old["match_id"] is None and old["status"] == "nova":
        # importação interrompida (app fechado no meio): refaz do zero
        with db.tx() as c:
            c.execute("DELETE FROM demos WHERE id=?", (old["id"],))
    elif old:
        return None
    stem = re.sub(r"\.dem(\.\w+)?$", "", src.name, flags=re.I)
    dst = DEMOS / f"{stem}_{hashlib.sha1(sig.encode()).hexdigest()[:8]}.dem"
    try:
        _copy_decompressed(src, dst)
        h = read_header(dst)
    except OSError as e:  # arquivo em uso, disco cheio...: tenta de novo na próxima volta
        log.warning("Não deu para copiar %s agora (%s). Tento de novo em instantes.", src.name, e)
        return None
    except Exception as e:
        log.warning("Ignorando %s: %s", src, e)
        with db.tx() as c:
            c.execute("INSERT OR IGNORE INTO demos(original,path,added_at,status) VALUES(?,?,?, 'erro')",
                      (sig, str(dst), db.now()))
        dst.unlink(missing_ok=True)
        return None

    if not _has_me(dst):  # você não está na demo: nunca vira partida sua
        log.info("Ignorando %s: você não jogou esta partida", src.name)
        with db.tx() as c:
            c.execute("INSERT OR IGNORE INTO demos(original,path,added_at,status) VALUES(?,?,?, 'nao_sua')",
                      (sig, str(dst), db.now()))
        dst.unlink(missing_ok=True)
        return None

    m = MATCH730.search(src.name)
    sc_mid = m.group(1) if m else None
    source = source_from_header(h)
    map_name = h.get("map_name")
    with db.tx() as c:
        demo_id = c.execute(
            """INSERT INTO demos(original,path,map,server_name,source,sharecode_matchid,file_time,added_at,status)
               VALUES(?,?,?,?,?,?,?,?, 'nova')""",
            (sig, str(dst), map_name, h.get("server_name"), source, sc_mid, st.st_mtime, db.now()),
        ).lastrowid
    fm = FACEIT_ID.search(src.name)
    fid = fm.group(1) if fm else None
    match_id = _find_match(map_name, sc_mid, st.st_mtime, fid) if (fid or sc_mid) else None
    if match_id is None and hint_match_id and _hint_ok(hint_match_id, map_name, fid):
        match_id = hint_match_id
    if match_id is None:
        match_id = _find_match(map_name, sc_mid, st.st_mtime, fid)
    with db.tx() as c:
        if match_id is None:
            match_id = c.execute(
                """INSERT INTO matches(started_at,ended_at,map,source,status,faceit_match_id)
                   VALUES(?,?,?,?, 'demo_pronta', ?)""",
                (st.st_mtime, st.st_mtime, map_name, "faceit" if fid else source, fid),
            ).lastrowid
        else:
            c.execute(
                """UPDATE matches SET demo_id=?, status='demo_pronta', map=COALESCE(map, ?),
                   source=CASE WHEN source IS NULL OR source='desconhecido' THEN ? ELSE source END WHERE id=?""",
                (demo_id, map_name, source, match_id),
            )
        c.execute("UPDATE matches SET demo_id=? WHERE id=?", (demo_id, match_id))
        c.execute("UPDATE demos SET match_id=?, status='vinculada' WHERE id=?", (match_id, demo_id))
    log.info("Demo %s (%s, %s) vinculada à partida %s", src.name, map_name, source, match_id)
    # o original só é apagado depois que a análise der certo (delete_original_after_analysis)
    return match_id


# ---------------------------------------------------------------- apagar o original
def delete_originals_on() -> bool:
    return db.kv_get("delete_originals") != "0"


def set_delete_originals(on: bool) -> None:
    db.kv_set("delete_originals", "1" if on else "0")


def _same_file(src: Path, sig: str) -> bool:
    """O arquivo ainda é o mesmo que foi importado (mesmo caminho, tamanho e data)."""
    try:
        path, size, mtime = sig.rsplit("|", 2)
        st = src.stat()
        return Path(path) == src.resolve() and st.st_size == int(size) and int(st.st_mtime) == int(mtime)
    except (OSError, ValueError):
        return False


def _delete_original(src: Path, copy: Path, sig: str) -> int:
    """Apaga o original só se a cópia do app existe e o arquivo é a demo que foi importada. Devolve os bytes liberados."""
    try:
        if not _is_demo(src) or not copy.is_file() or copy.stat().st_size == 0 or not _same_file(src, sig):
            return 0
        if copy.resolve().parent == src.resolve().parent:  # nunca apaga a própria cópia
            return 0
        size = src.stat().st_size
        src.unlink()
        log.info("Original apagado (a cópia fica no app): %s", src)
        return size
    except OSError as e:  # em uso, sem permissão...: fica lá, sem problema
        log.warning("Não deu para apagar o original %s: %s", src.name, e)
        return 0


def _has_me(dem: Path) -> bool:
    """Você está entre os jogadores da demo (sem steamid configurado ainda: aceita, como antes)."""
    me = db.kv_get("steamid")
    if not me:
        return True
    from demoparser2 import DemoParser
    try:
        players = DemoParser(str(dem)).parse_player_info()
    except Exception:
        return True
    ids = {str(s) for s in players["steamid"].tolist()}
    return not ids or me in ids


def delete_original_after_analysis(match_id: int) -> None:
    """Chamado quando a análise termina bem: aí sim o arquivo baixado pode sair."""
    if not delete_originals_on():
        return
    r = db.q1("""SELECT d.original, d.path FROM matches m JOIN demos d ON d.id=m.demo_id
                 WHERE m.id=? AND m.analyzed_at IS NOT NULL""", match_id)
    if r:
        _delete_original(Path(r["original"].rsplit("|", 2)[0]), Path(r["path"]), r["original"])


def _imported():
    for r in db.q("""SELECT d.original, d.path FROM demos d JOIN matches m ON m.id=d.match_id
                     WHERE d.status='vinculada' AND m.analyzed_at IS NOT NULL"""):
        src = Path(r["original"].rsplit("|", 2)[0])
        if _is_demo(src) and src.is_file() and _same_file(src, r["original"]):
            yield src, Path(r["path"]), r["original"]


def originals_left() -> dict:
    """Originais de demos já importadas que ainda estão no PC."""
    n = size = 0
    for src, _, _ in _imported():
        n += 1
        size += src.stat().st_size
    return {"n": n, "bytes": size}


def delete_imported_originals() -> dict:
    n = size = 0
    for src, copy, sig in list(_imported()):
        b = _delete_original(src, copy, sig)
        if b:
            n += 1
            size += b
    return {"n": n, "bytes": size}


def _find_match(map_name: str | None, sc_mid: str | None, ftime: float, fid: str | None = None) -> int | None:
    if fid:  # demo baixada da FACEIT: o nome do arquivo traz o id da partida
        r = db.q1("SELECT id FROM matches WHERE faceit_match_id=?", fid)
        if r:
            return r["id"]
    if sc_mid:
        r = db.q1("SELECT match_id FROM sharecodes WHERE match_id_valve=? AND match_id IS NOT NULL", sc_mid)
        if r:
            return r["match_id"]
    r = db.q1(
        """SELECT id FROM matches WHERE demo_id IS NULL AND map=? AND ended_at IS NOT NULL
           AND ended_at BETWEEN ? AND ? ORDER BY ABS(ended_at - ?) LIMIT 1""",
        map_name, ftime - LINK_WINDOW, ftime + 900, ftime,
    )
    return r["id"] if r else None


class DemoWatcher(threading.Thread):
    """Verifica as pastas a cada 15 s (polling: simples e sem hooks no sistema)."""

    def __init__(self, is_busy: Callable[[], bool], on_ready: Callable[[int], None] | None = None):
        super().__init__(daemon=True, name="demo-watcher")
        self.is_busy = is_busy
        self.on_ready = on_ready
        self.stop_evt = threading.Event()
        since = db.kv_get("demo_watch_since")
        if since is None:  # primeira execução: considera só demos dos últimos 2 dias
            since = str(time.time() - 2 * 86400)
            db.kv_set("demo_watch_since", since)
        self.since = float(since)

    def scan_once(self) -> None:
        for d in settings.demo_dirs():
            if not d.is_dir():
                continue
            for p in d.iterdir():
                if self.is_busy() or self.stop_evt.is_set():
                    return
                try:
                    if not p.is_file():
                        continue
                    if not _is_demo(p):
                        continue
                    mt = p.stat().st_mtime
                    if mt < self.since or time.time() - mt < STABLE_SECS:
                        continue
                    mid = import_demo(p)
                    if mid and self.on_ready:
                        self.on_ready(mid)
                except Exception:
                    log.exception("Erro importando %s", p)

    def run(self) -> None:
        while not self.stop_evt.wait(15):
            if not self.is_busy():
                self.scan_once()
