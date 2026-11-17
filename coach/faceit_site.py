"""Baixa as demos das SUAS partidas da FACEIT pelo site, como você faria à mão.

- Você entra na FACEIT numa janela do próprio app (WebView2, o Edge do Windows). O login fica salvo
  em data/webview, como num navegador normal. O app nunca vê nem guarda a sua senha.
- O app abre o SEU histórico de partidas no site e, para cada partida que ainda não tem a demo,
  abre a sala e clica em "Assistir à demonstração". Uma partida por vez, com pausa entre elas.
  Nada de API: é o mesmo caminho que você faria no navegador.
- Só as partidas do seu histórico, só as dos últimos 30 dias (depois disso a FACEIT apaga a demo).
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx
from fastapi import APIRouter, HTTPException, Request

from . import db, scout
from .config import settings
from .demos import import_demo
from .faceit import INBOX

log = logging.getLogger("coach.faceit_site")

SITE = "https://www.faceit.com/pt-br"
NICK = re.compile(r"[A-Za-z0-9_-]{2,32}")
MAX_AGE = 30 * 86400
PAUSE = (25, 40)          # segundos entre uma partida e outra
MISSES_TO_STOP = 3        # salas seguidas sem o botão da demo: o resto já expirou
SKIP_KEY = "faceit_sem_demo"  # salas que já vimos sem demo (não abre de novo)
AUTO_KEY = "faceit_auto"      # baixar sozinho depois das partidas (padrão: ligado)
LOGGED_KEY = "faceit_logado"  # a última vez que olhamos, você estava logado na janela do app
RECENT = 86400                # sala sem botão há menos de 1 dia: a demo ainda pode aparecer

# ---------------- scripts rodados na página (só leitura e o clique no botão) ----------------
LOGGED_OUT_JS = r"""
(() => {
  const t = [...document.querySelectorAll('button, a')].map(b => (b.innerText || '').trim().toUpperCase());
  return t.includes('LOGIN') || t.includes('CRIAR CONTA') || t.includes('INICIAR SESSÃO');
})()
"""

LIST_JS = r"""
(() => {
  window.scrollTo(0, document.body.scrollHeight);
  document.querySelectorAll('*').forEach(e => {
    if (e.scrollHeight > e.clientHeight + 50 && /auto|scroll/.test(getComputedStyle(e).overflowY)) e.scrollTop = e.scrollHeight;
  });
  const out = {};
  for (const a of document.querySelectorAll('a[href*="/room/"]')) {
    const m = a.href.match(/room\/(1-[0-9a-f-]{36})/i);
    if (!m || out[m[1]]) continue;
    out[m[1]] = ((a.closest('tr') || a).innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  }
  const steam = [...document.querySelectorAll('a[href*="steamcommunity.com/profiles/"]')]
    .map(a => (a.href.match(/profiles\/(7656\d{13})/) || [])[1]).find(Boolean);
  return JSON.stringify({rows: out, steamid: steam || null});
})()
"""

_FIND = r"""
const __re = /^(assistir à demonstração|assistir a demonstração|assistir demo|watch demo)$/i;
const __find = () => [...document.querySelectorAll('a, button, [role=button], span, div')]
  .filter(e => __re.test((e.innerText || '').trim()) && e.offsetParent !== null)
  .sort((a, b) => a.innerText.length - b.innerText.length)[0];
"""

BUTTON_JS = "(() => {" + _FIND + r"""
  if (__find()) return 'achou';
  return document.querySelector('a[href*="/players/"]') ? 'carregou' : 'carregando';
})()"""

CLICK_JS = "(() => {" + _FIND + r"""
  const el = __find();
  if (!el) return 'sem_botao';
  window.__coachUrls = [];
  const keep = (u) => { try { if (u) window.__coachUrls.push(String(u)); } catch (e) {} };
  if (!window.__coachHooked) {
    window.__coachHooked = true;
    // o app baixa o link ele mesmo, sem abrir janela nova (também pega window.open() + w.location = url)
    window.open = function (u) {
      keep(u);
      const loc = { set href(x) { keep(x); }, assign: keep, replace: keep };
      return { closed: false, close() {}, focus() {}, document: { write() {}, close() {} },
               get location() { return loc; }, set location(x) { keep(x); } };
    };
    const isDemo = (u) => u && !u.includes('/room/') && /\.dem|demo/i.test(u);
    const ac = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () { keep(this.href); if (!isDemo(this.href)) return ac.call(this); };
    document.addEventListener('click', (e) => {
      const a = e.target && e.target.closest ? e.target.closest('a') : null;
      if (a && isDemo(a.href)) { keep(a.href); e.preventDefault(); }
    }, true);
  }
  const a = el.closest('a');
  if (a && a.href && !a.href.includes('/room/')) keep(a.href);
  el.click();
  return 'clicou';
})()"""

URLS_JS = "JSON.stringify(window.__coachUrls || [])"

MONTHS = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9,
          "out": 10, "nov": 11, "dez": 12}
DATE_RE = re.compile(r"(\d{1,2}) (jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\.?(?: (\d{4}))?(?: (\d{1,2}):(\d{2}))?", re.I)


def parse_when(text: str, now: float | None = None) -> float | None:
    """'seg. 16 nov. 17:42' -> horário Unix (ano atual; se cair no futuro, ano passado)."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    now = now or time.time()
    day, mon = int(m.group(1)), MONTHS[m.group(2).lower()]
    hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
    year = int(m.group(3)) if m.group(3) else datetime.fromtimestamp(now).year
    try:
        ts = datetime(year, mon, day, hh, mm).timestamp()
    except ValueError:
        return None
    if not m.group(3) and ts > now + 86400:
        ts = datetime(year - 1, mon, day, hh, mm).timestamp()
    return ts


def demo_url(urls: list[str]) -> str | None:
    for u in urls:
        if u.startswith("http") and "/room/" not in u and re.search(r"\.dem|demo", u, re.I):
            return u
    return None


def file_name(url: str, fid: str) -> str:
    name = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1] or "demo.dem.zst"
    name = re.sub(r"[^\w.\-]", "_", name)
    if not re.search(r"\.dem(\.\w+)?$", name):
        name += ".dem.zst" if ".zst" in url else ".dem.gz"
    return name if fid.lower() in name.lower() else f"{fid}_{name}"


def auto_on() -> bool:
    return db.kv_get(AUTO_KEY) != "0"


def set_auto(on: bool) -> None:
    db.kv_set(AUTO_KEY, "1" if on else "0")


def pending(rows: dict[str, str], now: float | None = None) -> list[tuple[str, float | None]]:
    """Salas sem demo no app (mais novas primeiro): as do histórico do site (só mostra as 30 últimas)
    e as partidas FACEIT suas que o app já conhecia mas ficaram esperando a demo."""
    now = now or time.time()
    found = {fid: parse_when(text, now) for fid, text in rows.items()}
    for r in db.q("""SELECT faceit_match_id, COALESCE(played_at, ended_at, started_at) quando FROM matches
                     WHERE faceit_match_id IS NOT NULL AND demo_id IS NULL"""):
        found.setdefault(r["faceit_match_id"], r["quando"])
    skip = set(json.loads(db.kv_get(SKIP_KEY) or "[]"))
    have = {r["faceit_match_id"] for r in db.q(
        "SELECT faceit_match_id FROM matches WHERE faceit_match_id IS NOT NULL AND demo_id IS NOT NULL")}
    out = []
    for fid, when in found.items():
        if fid in have or fid in skip or (when and now - when > MAX_AGE):
            continue
        out.append((fid, when))
    return sorted(out, key=lambda x: -(x[1] or now))


class FaceitSite:
    """Uma janela da FACEIT dentro do app. Só existe no modo com janela (coach.app)."""

    def __init__(self, on_demo: Callable[[int], None]):
        self.on_demo = on_demo
        self.win = None
        self._after_login = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.state: dict = {"rodando": False, "fase": None, "feitas": 0, "total": 0, "baixadas": 0,
                            "sem_demo": 0, "msg": None, "erro": None, "logado": None, "alvo": None}

    # ---------- janela ----------
    def _window(self, url: str, visible: bool):
        import webview
        # o título é a instrução: quem olha a janela só vê o site da FACEIT
        title = ("Entre na sua conta da FACEIT e depois feche esta janela · CS2 Coach" if visible
                 else "FACEIT · CS2 Coach baixando demos (pode deixar minimizada)")
        if self.win is not None:
            try:
                self.win.set_title(title)
                self.win.load_url(url)
                (self.win.show if visible else self.win.minimize)()
                return self.win
            except Exception:
                self.win = None
        self.win = webview.create_window(title, url, width=1200, height=820, focus=visible,
                                         minimized=not visible, background_color="#0a0c10")
        self.win.events.closed += self._closed
        self.win.events.loaded.wait(30)
        return self.win

    def _closed(self) -> None:
        self.win = None
        if self.state["rodando"]:
            self._stop.set()
        elif self._after_login:  # fechou a janela de login: começa a baixar
            self._after_login = False
            threading.Thread(target=self.start, daemon=True).start()

    def _js(self, code: str):
        if self.win is None:
            raise RuntimeError("janela fechada")
        return self.win.evaluate_js(code)

    def _goto(self, url: str) -> None:
        if self.win is None:  # janela recriada depois de um problema
            self._window(url, False)
            time.sleep(2)
            return
        self.win.events.loaded.clear()
        self.win.load_url(url)
        self.win.events.loaded.wait(60)  # a sala da FACEIT é pesada; minimizada, demora mais
        time.sleep(2)

    @staticmethod
    def history_url() -> str:
        nick = settings.faceit_nickname or ""
        if not NICK.fullmatch(nick):
            raise RuntimeError("Configure seu nick da FACEIT primeiro.")
        return f"{SITE}/players/{nick}/cs2/history"

    def login(self) -> None:
        """Abre a FACEIT para você entrar. Ao fechar a janela, o app já começa a baixar suas demos."""
        self._after_login = True
        self._window(self.history_url(), True)

    # ---------- automático ----------
    def start_auto(self) -> None:
        threading.Thread(target=self._auto, daemon=True, name="faceit-auto").start()

    def _auto(self) -> None:
        """Uma conferida quando o app abre (o resto é pelo botão)."""
        time.sleep(15)
        try:
            if auto_on() and db.kv_get(LOGGED_KEY) == "1" and settings.faceit_nickname and not self.state["rodando"]:
                log.info("FACEIT: conferindo partidas novas (app aberto)")
                self.start()
        except Exception:
            log.exception("FACEIT ao abrir")

    # ---------- sincronização ----------
    def status(self) -> dict:
        return dict(self.state)

    def stop(self) -> None:
        self._stop.set()

    def start(self) -> bool:
        with self._lock:
            if self.state["rodando"]:
                return False
            self._stop.clear()
            self.state.update(rodando=True, fase="abrindo", feitas=0, total=0, baixadas=0, sem_demo=0, msg=None, erro=None,
                              alvo=None)
        threading.Thread(target=self._run, daemon=True, name="faceit-site").start()
        return True

    def start_scout(self, nick: str, n: int) -> bool:
        """Baixa as últimas n partidas de outro jogador para comparar (não vira partida sua)."""
        scout.json_file(nick)  # valida o nick
        with self._lock:
            if self.state["rodando"]:
                return False
            self._stop.clear()
            self.state.update(rodando=True, fase="abrindo", feitas=0, total=0, baixadas=0, sem_demo=0, msg=None,
                              erro=None, alvo=nick)
        threading.Thread(target=self._run_scout, args=(nick, n), daemon=True, name="faceit-scout").start()
        return True

    def _run_scout(self, nick: str, n: int) -> None:
        pool = None
        try:
            self._window(f"{SITE}/players/{nick}/cs2/history", False)
            self.state["fase"] = "lendo histórico"
            rows, steamid = self._history()
            if self._js(LOGGED_OUT_JS):
                raise RuntimeError("Você não está logado na FACEIT dentro do app. Clique em Entrar na FACEIT.")
            if not rows or not steamid:
                raise RuntimeError(f"Não achei o histórico de {nick} na FACEIT (confira o nick).")
            now = time.time()
            done = scout.known_rooms(nick)
            todo = [(fid, parse_when(text, now)) for fid, text in list(rows.items())[:n]]
            todo = [(fid, w) for fid, w in todo if fid not in done and not (w and now - w > MAX_AGE)]
            self.state.update(total=len(todo), fase="baixando")
            log.info("FACEIT: comparando com %s, %d partidas para baixar", nick, len(todo))
            for i, (fid, when) in enumerate(todo):
                if i and not self._wait(random.uniform(*PAUSE)):
                    break
                self.state["msg"] = f"Partida {i + 1} de {len(todo)}"
                url = self._link(fid, when, remember=False)
                if url:
                    try:
                        path = self._download(url, fid, scout.DIR / "baixando")
                        self.state["msg"] = f"Analisando partida {i + 1} de {len(todo)}"
                        if pool is None:
                            import multiprocessing as mp
                            from concurrent.futures import ProcessPoolExecutor
                            pool = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
                        pool.submit(scout.analyze_job, str(path), fid, steamid, nick, when).result()
                        self.state["baixadas"] += 1
                    except Exception as e:
                        if self._stop.is_set():
                            break
                        log.warning("FACEIT: partida %s de %s falhou (%s); sigo para a próxima", fid, nick, e)
                        pool = None if "BrokenProcessPool" in type(e).__name__ else pool
                elif url is None:
                    self.state["sem_demo"] += 1
                self.state["feitas"] = i + 1
                if self._stop.is_set():
                    break
            if not scout.load(nick):
                raise RuntimeError(f"Nenhuma partida recente de {nick} com demo disponível.")
            self.state["msg"] = "Interrompido" if self._stop.is_set() else "Pronto"
        except Exception as e:
            log.warning("FACEIT comparação (%s): %s", nick, e)
            self.state["erro"] = str(e)
        finally:
            if pool is not None:
                pool.shutdown(wait=False)
            self.state.update(rodando=False, fase=None)
            if self.win is not None:
                try:
                    self.win.destroy()
                except Exception:
                    pass
                self.win = None

    def _wait(self, secs: float) -> bool:
        """Pausa entre uma sala e outra. False se mandaram parar."""
        return not self._stop.wait(secs)

    def _run(self) -> None:
        try:
            self._window(self.history_url(), False)
            self.state["fase"] = "lendo histórico"
            rows, steamid = self._history()
            if steamid and not db.kv_get("steamid"):
                # quem é você: o SteamID ligado ao SEU perfil da FACEIT (o nick que você digitou)
                from . import analysis
                analysis.set_me(steamid)
                log.info("FACEIT: você = %s (link da Steam no seu perfil da FACEIT)", steamid)
            logged_out = bool(self._js(LOGGED_OUT_JS))
            self.state["logado"] = not logged_out
            db.kv_set(LOGGED_KEY, "0" if logged_out else "1")
            if logged_out:
                raise RuntimeError("Você não está logado na FACEIT dentro do app. Clique em Entrar na FACEIT.")
            if not rows:
                raise RuntimeError("Não achei partidas no seu histórico da FACEIT.")
            todo = pending(rows)
            self.state.update(total=len(todo), fase="baixando")
            log.info("FACEIT pelo site: %d partidas no histórico, %d sem demo no app", len(rows), len(todo))
            misses = 0
            for i, (fid, when) in enumerate(todo):
                if i and not self._wait(random.uniform(*PAUSE)):
                    break
                if self._stop.is_set():
                    break
                self.state["msg"] = f"Partida {i + 1} de {len(todo)}"
                try:
                    got = self._one(fid, when)
                except Exception as e:
                    if self._stop.is_set():
                        break
                    log.warning("FACEIT: partida %s falhou (%s); sigo para a próxima", fid, e)
                    got = False
                self.state["feitas"] = i + 1
                if got:
                    misses = 0
                    self.state["baixadas"] += 1
                elif got is None:
                    misses += 1
                    self.state["sem_demo"] += 1
                    if misses >= MISSES_TO_STOP:
                        log.info("FACEIT: %d salas seguidas sem demo, o resto já expirou", misses)
                        break
            self.state["msg"] = "Interrompido" if self._stop.is_set() else "Pronto"
        except Exception as e:
            log.warning("FACEIT pelo site: %s", e)
            self.state["erro"] = str(e)
        finally:
            self.state.update(rodando=False, fase=None)
            if self.win is not None:
                try:
                    self.win.destroy()
                except Exception:
                    pass
                self.win = None

    def _link(self, fid: str, when: float | None, remember: bool = True) -> str | bool | None:
        """Abre a sala e clica em Assistir demo. URL da demo; None: a sala não tem demo; False: falhou."""
        try:
            return self._link_once(fid, when, remember)
        except Exception as e:
            if self._stop.is_set():
                raise
            log.warning("FACEIT: a sala %s não respondeu (%s); sigo para a próxima", fid, e)
            self._reset_window()
            return False

    def _reset_window(self) -> None:
        win, self.win = self.win, None
        if win is not None:
            try:
                win.events.closed -= self._closed  # fechar de propósito não é "você fechou a janela"
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

    def _link_once(self, fid: str, when: float | None, remember: bool) -> str | bool | None:
        self._goto(f"{SITE}/cs2/room/{fid}")
        found = "carregando"
        for _ in range(25):
            found = self._js(BUTTON_JS)
            if found == "achou":
                break
            time.sleep(1)
        if found != "achou":
            if found == "carregou":  # página aberta, mas sem o botão: demo expirada ou indisponível
                if when and time.time() - when < RECENT:
                    return False  # partida recente: a FACEIT ainda está preparando a demo
                if not remember:
                    return None
                skip = set(json.loads(db.kv_get(SKIP_KEY) or "[]")) | {fid}
                db.kv_set(SKIP_KEY, json.dumps(sorted(skip)))
                return None
            return False
        time.sleep(random.uniform(1, 3))
        if self._js(CLICK_JS) != "clicou":
            return False
        url = None
        for _ in range(30):
            time.sleep(1)
            url = demo_url(json.loads(self._js(URLS_JS) or "[]"))
            if url:
                break
        if not url:
            log.warning("FACEIT: cliquei em Assistir demo na sala %s, mas nenhum link apareceu", fid)
            return False
        return url

    def _history(self) -> tuple[dict[str, str], str | None]:
        """Salas do histórico aberto na janela (mais novas primeiro) e o SteamID do dono do perfil."""
        rows: dict[str, str] = {}
        steamid = None
        for _ in range(8):  # rola a lista algumas vezes para carregar mais partidas
            time.sleep(2)
            d = json.loads(self._js(LIST_JS) or "{}")
            rows.update(d.get("rows") or {})
            steamid = steamid or d.get("steamid")
        return rows, steamid

    def _one(self, fid: str, when: float | None) -> bool | None:
        """True: demo importada. None: a sala não tem demo. False: falhou (tenta de novo outra vez)."""
        url = self._link(fid, when)
        if not url:
            return url
        path = self._download(url, fid, INBOX)
        mid = import_demo(path)
        if not mid:
            return False
        if when:
            with db.tx() as c:
                c.execute("UPDATE matches SET played_at=COALESCE(played_at, ?), ended_at=COALESCE(ended_at, ?) WHERE id=?",
                          (when, when, mid))
        log.info("FACEIT: demo da sala %s importada (partida %s)", fid, mid)
        self.on_demo(mid)
        return True

    def _download(self, url: str, fid: str, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / file_name(url, fid)
        tmp = dst.with_name(dst.name + ".part")
        with httpx.Client(timeout=60, follow_redirects=True) as c, c.stream("GET", url) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    if self._stop.is_set():
                        raise RuntimeError("interrompido")
                    f.write(chunk)
        tmp.replace(dst)
        return dst


def make_router(site: FaceitSite | None) -> APIRouter:
    from .settings_api import same_origin
    r = APIRouter()

    def need() -> FaceitSite:
        if site is None:
            raise HTTPException(501, "Só funciona no app com janela.")
        return site

    @r.get("/api/faceit-site")
    def status():
        return {**site.status(), "auto": auto_on(), "entrou": db.kv_get(LOGGED_KEY) == "1",
                "expirou": db.kv_get(LOGGED_KEY) == "0"} if site else {"indisponivel": True}

    @r.post("/api/faceit-site/login")
    def login(request: Request):
        same_origin(request)
        s = need()
        try:
            s.history_url()
        except RuntimeError as e:
            raise HTTPException(400, str(e))
        threading.Thread(target=s.login, daemon=True).start()
        return {"ok": True}

    @r.post("/api/faceit-site/sync")
    def sync(request: Request):
        same_origin(request)
        need().start()
        return need().status()

    @r.post("/api/faceit-site/auto")
    async def auto(request: Request):
        same_origin(request)
        set_auto(bool((await request.json()).get("on")))
        return {"auto": auto_on()}

    @r.get("/api/comparar")
    def compare_list():
        return {"jogadores": scout.listed(), "disponivel": site is not None}

    @r.get("/api/comparar/{nick}")
    def compare(nick: str):
        try:
            ele = scout.load(nick)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not ele:
            raise HTTPException(404)
        n = max(1, (ele.get("total") or {}).get("partidas") or 10)
        return {"ele": ele, "eu": scout.mine(n), "partidas": n}

    @r.post("/api/comparar")
    async def compare_start(request: Request):
        same_origin(request)
        body = await request.json()
        n = 30 if int(body.get("partidas") or 10) >= 30 else 10
        try:
            need().start_scout(str(body.get("nick") or "").strip(), n)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return need().status()

    @r.delete("/api/comparar/{nick}")
    def compare_remove(nick: str, request: Request):
        same_origin(request)
        try:
            scout.remove(nick)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @r.post("/api/faceit-site/stop")
    def stop(request: Request):
        same_origin(request)
        need().stop()
        return need().status()

    return r

