"""Liga tudo: GSI, pipeline pós-partida, monitor de demos e fila de análise."""
from __future__ import annotations

import ctypes
import logging
import logging.handlers
import os
import itertools
import multiprocessing as mp
import queue
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

# Nunca disputar CPU com o jogo: a leitura de demos usa no máximo 2 núcleos
# (precisa vir antes do primeiro uso do demoparser2) e o processo roda com prioridade baixa.
os.environ.setdefault("RAYON_NUM_THREADS", "2")
os.environ.setdefault("POLARS_MAX_THREADS", "2")
try:
    BELOW_NORMAL_PRIORITY_CLASS = 0x4000
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.SetPriorityClass(k32.GetCurrentProcess(), BELOW_NORMAL_PRIORITY_CLASS)
except Exception:
    pass

from . import aim, analysis, db, demos, faceit, radar, steam  # noqa: E402
from .config import LOGS, settings
from .demos import DemoWatcher
from .gamewatch import cs2_in_foreground
from .poller import MatchPoller
from .gsi import Tracker
from .gsi_cfg import install
from .pipeline import Pipeline

log = logging.getLogger("coach")


def setup_logging(console: bool = True) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(LOGS / "coach.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    # httpx registra a URL inteira de cada pedido, e a da Steam leva a chave e o código: nunca no log
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


class Analyzer(threading.Thread):
    """Fila de trabalho.

    Cada demo é analisada num processo separado (até WORKERS ao mesmo tempo, 1 com o CS aberto):
    a leitura pesada não trava a interface e várias demos andam juntas.
    """

    ANALISAR = 0
    WORKERS = 3

    def __init__(self, busy, on_done=None, in_game=None, workers: int | None = None):
        super().__init__(daemon=True, name="analyzer")
        self.busy = busy
        self.on_done = on_done
        self.in_game = in_game or (lambda: False)
        self.workers = workers or self.WORKERS
        self.q: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._free = threading.Condition(self._lock)
        self.pending: dict[int, set[int]] = {self.ANALISAR: set()}
        self.done = {self.ANALISAR: 0}
        self.running: set[tuple[int, int]] = set()
        self.paused = False
        self._pool: ProcessPoolExecutor | None = None

    def _put(self, kind: int, mid: int) -> None:
        with self._lock:
            if mid in self.pending[kind] or (kind, mid) in self.running:
                return
            self.pending[kind].add(mid)
        self.q.put((kind, next(self._seq), mid))

    def submit(self, match_id: int) -> None:
        self._put(self.ANALISAR, match_id)

    def progress(self) -> dict:
        with self._lock:
            run = set(self.running)
            na, da = len(self.pending[self.ANALISAR]), self.done[self.ANALISAR]
        a_cur = len(run)
        if not (na or run):
            self.done = {self.ANALISAR: 0}
        return {
            "pausado": self.paused and bool(na or run),
            "atual": "analise" if run else None,
            "rodando": a_cur,
            "analise": {"feitas": da, "total": da + na + a_cur} if (na or a_cur) else None,
        }

    def _wait_free(self) -> None:
        while self.busy():
            self.paused = True
            threading.Event().wait(10)
        self.paused = False

    def _limit(self) -> int:
        try:
            return 1 if self.in_game() else self.workers
        except Exception:
            return 1

    def _pool_get(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=self.workers, mp_context=mp.get_context("spawn"))
        return self._pool

    def run(self) -> None:
        if settings.gsi_enabled:  # dá tempo do GSI avisar (heartbeat de 30 s) se o CS já estava num mapa
            threading.Event().wait(40)
        while True:
            kind, _, mid = self.q.get()
            self._wait_free()
            with self._free:  # espera uma vaga (com o CS aberto, uma análise por vez)
                while len(self.running) >= self._limit():
                    self._free.wait(5)
                self.pending[kind].discard(mid)
                self.running.add((kind, mid))
            log.info("Analisando partida %s (processo separado)", mid)
            try:
                fut = self._pool_get().submit(_analyze_job, mid)
            except Exception:  # pool quebrado (processo morreu): recria na próxima
                self._pool = None
                fut = self._pool_get().submit(_analyze_job, mid)
            fut.add_done_callback(lambda f, mid=mid: threading.Thread(
                target=self._after, args=(mid, f), daemon=True, name=f"pos-{mid}").start())

    def _release(self, kind: int, mid: int) -> None:
        with self._free:
            self.running.discard((kind, mid))
            self.done[kind] += 1
            self._free.notify_all()

    def _after(self, mid: int, fut) -> None:
        try:
            try:
                fut.result()
            except BrokenProcessPool:
                self._pool = None
                raise
            log.info("Partida %s analisada", mid)
            demos.delete_original_after_analysis(mid)
            try:
                steam.refresh_profiles()  # fotos de perfil dos jogadores novos
            except Exception:
                log.warning("Falha ao buscar perfis da Steam")
            if self.on_done:
                self.on_done(mid)
        except Exception:
            log.exception("Falha ao processar a partida %s", mid)
            with db.tx() as c:
                c.execute("UPDATE matches SET status='erro', note='Falha ao ler a demo (veja o log)' WHERE id=?", (mid,))
        finally:
            self._release(self.ANALISAR, mid)


def _analyze_job(mid: int) -> None:
    """Roda no processo de análise: lê a demo e grava no banco."""
    analysis.analyze(mid)


def pause_in_game() -> bool:
    return db.kv_get("pause_in_game") == "1"


def set_pause_in_game(on: bool) -> None:
    db.kv_set("pause_in_game", "1" if on else "0")


class Services:
    def __init__(self, on_analyzed=None):
        analysis.migrate()
        try:
            cfg = install()
            log.info("GSI: %s", cfg or "desligado (padrão). Partidas detectadas pelas APIs e pelas demos.")
        except SystemExit as e:
            log.warning("%s", e)
        log.info("FACEIT: %s | Steam share codes: %s",
                 "ok" if faceit.configured() else "não configurado",
                 "ok" if steam.configured() else "não configurado")
        self.tracker = Tracker()
        # "jogando" = CS2 em primeiro plano (ou, com GSI ligado, em qualquer mapa)
        self.in_game = lambda: cs2_in_foreground() or (settings.gsi_enabled and self.tracker.busy)  # noqa: E731
        # a fila só pausa no jogo se a opção estiver ligada em Configurações (vem desligada)
        busy = lambda: pause_in_game() and self.in_game()  # noqa: E731
        self.busy = busy
        self.analyzer = Analyzer(busy, on_analyzed, in_game=self.in_game)
        self.pipeline = Pipeline(busy, self.analyzer.submit)
        self.tracker.on_match_end = self.pipeline.match_ended
        self.watcher = DemoWatcher(busy, self.analyzer.submit)
        self.poller = MatchPoller(busy, self.analyzer.submit) if not settings.gsi_enabled else None

    @staticmethod
    def _radars() -> None:
        try:
            radar.extract_all()
            radar.extract_shots()
        except Exception:
            log.exception("Falha ao extrair radares do CS2")
        try:
            steam.refresh_profiles()
        except Exception:
            log.exception("Falha ao buscar perfis da Steam")

    def _ranks(self) -> None:
        """Rank Premier das partidas analisadas antes do campo existir, e level FACEIT (com a chave)."""
        try:
            ids = [r["match_id"] for r in db.q(
                "SELECT DISTINCT match_id FROM demo_players WHERE rank IS NULL")]
        except Exception:
            ids = []
        for mid in ids:
            while self.busy():
                threading.Event().wait(10)
            try:
                analysis.fill_ranks(mid)
            except Exception:
                log.warning("Não deu para ler o rank da partida %s", mid)
        # tiros (mira) das partidas analisadas antes da página de mira existir
        try:
            pend = aim.missing()
        except Exception:
            pend = []
        for mid in pend:
            while self.busy():
                threading.Event().wait(10)
            try:
                aim.fill(mid)
            except Exception:
                log.warning("Não deu para ler os tiros da partida %s", mid)
        if pend:
            log.info("Tiros lidos de %d partida(s)", len(pend))
        try:
            faceit.refresh_levels()
        except Exception:
            log.warning("Falha ao buscar levels da FACEIT")

    def start(self) -> None:
        for t in (self.analyzer, self.pipeline, self.watcher, self.poller):
            if t:
                t.start()
        # radares do jogo (só na primeira vez ou quando o formato muda)
        threading.Thread(target=self._radars, daemon=True, name="radars").start()
        threading.Thread(target=self._ranks, daemon=True, name="ranks").start()
        # demos não analisadas (app fechado no meio) ou analisadas por uma versão antiga
        for r in db.q("""SELECT m.id, m.source, d.path FROM matches m JOIN demos d ON d.id=m.demo_id
                         WHERE m.status!='erro'
                         AND (m.analyzed_at IS NULL OR COALESCE(m.analysis_version, 1) < ?)""", analysis.VERSION):
            self.analyzer.submit(r["id"])
        log.info("Pastas de demo monitoradas: %s",
                 ", ".join(str(d) for d in settings.demo_dirs() if d.is_dir()))
