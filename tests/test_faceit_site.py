import json
from datetime import datetime

from fastapi.testclient import TestClient

from coach import analysis, db, faceit_site
from coach.gsi import Tracker
from coach.server import create_app

A = "1-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
B = "1-11111111-2222-3333-4444-555555555555"
C = "1-99999999-8888-7777-6666-555555555555"


def test_parse_when_uses_current_or_last_year():
    now = datetime(2026, 11, 17, 12, 0).timestamp()
    assert faceit_site.parse_when("seg. 16 nov. 17:42 V 22 : 20", now) == datetime(2026, 11, 16, 17, 42).timestamp()
    assert faceit_site.parse_when("qua. 30 dez.", now) == datetime(2025, 12, 30).timestamp()
    assert faceit_site.parse_when("sem data", now) is None


def test_demo_url_and_file_name():
    urls = ["https://www.faceit.com/pt-br/cs2/room/" + A, "https://demos-us.faceit-cdn.net/cs2/" + A + "-1-1.dem.zst?sig=x"]
    url = faceit_site.demo_url(urls)
    assert url == urls[1]
    assert faceit_site.file_name(url, A) == A + "-1-1.dem.zst"
    assert faceit_site.file_name("https://cdn.example/x/demo.dem.gz?t=1", A) == A + "_demo.dem.gz"
    assert faceit_site.demo_url(["about:blank"]) is None


def test_pending_skips_known_old_and_expired(tmp_path):
    db.use(tmp_path / "t.db")
    analysis.migrate()
    now = datetime(2026, 11, 17, 12, 0).timestamp()
    with db.tx() as c:
        c.execute("INSERT INTO demos(id, original, path, added_at, status) VALUES(1,'y','x',1,'analisada')")
        c.execute("INSERT INTO matches(started_at, source, status, faceit_match_id, demo_id) VALUES(1,'faceit','analisada',?,1)", (A,))
    db.kv_set(faceit_site.SKIP_KEY, json.dumps([C]))
    rows = {A: "dom. 15 nov.", B: "seg. 16 nov. 17:42", C: "seg. 16 nov.", "1-00000000-0000-0000-0000-000000000000": "1 set."}
    assert [fid for fid, _ in faceit_site.pending(rows, now)] == [B]


def test_routes_need_window_and_app_header(tmp_path):
    db.use(tmp_path / "t.db")
    cli = TestClient(create_app(Tracker()))
    assert cli.get("/api/faceit-site").json() == {"indisponivel": True}
    assert cli.post("/api/faceit-site/sync").status_code == 403
    assert cli.post("/api/faceit-site/sync", headers={"X-Coach": "1"}).status_code == 501


def test_pending_includes_known_rooms_waiting_for_demo(tmp_path):
    db.use(tmp_path / "t.db")
    analysis.migrate()
    now = datetime(2026, 11, 17, 12, 0).timestamp()
    old = datetime(2026, 11, 1, 20, 5).timestamp()
    with db.tx() as c:
        c.execute("INSERT INTO matches(started_at, played_at, source, status, faceit_match_id) VALUES(?,?,'faceit','aguardando_demo',?)", (old, old, C))
        c.execute("INSERT INTO matches(started_at, played_at, source, status, faceit_match_id) VALUES(1,1,'faceit','aguardando_demo',?)", (A,))
    got = faceit_site.pending({B: "seg. 16 nov. 17:42"}, now)
    assert got == [(B, datetime(2026, 11, 16, 17, 42).timestamp()), (C, old)]


def test_auto_toggle(tmp_path):
    db.use(tmp_path / "t.db")
    assert faceit_site.auto_on()
    faceit_site.set_auto(False)
    assert not faceit_site.auto_on()


def test_compare_routes_read_scout_files(tmp_path, monkeypatch):
    from coach import scout
    db.use(tmp_path / "t.db")
    monkeypatch.setattr(scout, "DIR", tmp_path / "scout")
    scout.DIR.mkdir()
    scout.json_file("Fulano").write_text(json.dumps({"nick": "Fulano", "salas": [A], "total": {"partidas": 3, "adr": 80.0}}))
    cli = TestClient(create_app(Tracker()))
    assert cli.get("/api/comparar").json()["jogadores"][0] == {"nick": "Fulano", "partidas": 3, "atualizado": None}
    assert cli.get("/api/comparar/fulano").json()["ele"]["total"]["adr"] == 80.0
    assert cli.get("/api/comparar/outro").status_code == 404
    assert scout.known_rooms("Fulano") == {A}
    assert cli.delete("/api/comparar/Fulano", headers={"X-Coach": "1"}).json() == {"ok": True}
    assert scout.listed() == []


def test_scout_rejects_bad_nick():
    from coach import scout
    import pytest
    with pytest.raises(ValueError):
        scout.db_file("../x")


def test_closing_login_window_starts_download(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    site = faceit_site.FaceitSite(on_demo=lambda mid: None)
    started = []
    monkeypatch.setattr(site, "start", lambda: started.append(1))
    site._closed()                      # janela fechada sem ser a de login: nada
    site._after_login = True
    site._closed()                      # fechou a janela de login: começa a baixar
    import time
    time.sleep(0.2)
    assert started == [1] and not site._after_login


def test_overview_and_aim_say_when_nothing_is_analyzed(tmp_path):
    db.use(tmp_path / "t.db")
    analysis.migrate()
    cli = TestClient(create_app(Tracker()))
    assert cli.get("/api/overview").json() == {"me": None, "analisadas": 0}
    assert cli.get("/api/mira").json()["analisadas"] == 0


def test_status_says_when_login_expired(tmp_path):
    db.use(tmp_path / "t.db")
    site = faceit_site.FaceitSite(on_demo=lambda mid: None)
    cli = TestClient(create_app(Tracker(), faceit_site=site))
    assert cli.get("/api/faceit-site").json()["expirou"] is False      # nunca entrou: é o passo a passo, não aviso
    db.kv_set(faceit_site.LOGGED_KEY, "0")
    st = cli.get("/api/faceit-site").json()
    assert st["expirou"] is True and st["entrou"] is False
