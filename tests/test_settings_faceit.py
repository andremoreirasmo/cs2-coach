from fastapi.testclient import TestClient

from coach import db, settings_api, vault
from coach.gsi import Tracker
from coach.server import create_app

H = {"X-Coach": "1"}


def _client(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    store = {}
    monkeypatch.setattr(vault, "get", lambda n: store.get(n, ""))
    monkeypatch.setattr(vault, "set", lambda n, v: store.__setitem__(n, v))
    opened = []
    monkeypatch.setattr(settings_api.webbrowser, "open", opened.append)
    return TestClient(create_app(Tracker())), store, opened


def test_nick_only_without_key(tmp_path, monkeypatch):
    cli, store, opened = _client(tmp_path, monkeypatch)
    r = cli.post("/api/settings/faceit", json={"nickname": "jogador1"}, headers=H)
    assert r.status_code == 200 and r.json()["faceit"]["ok"] and not r.json()["faceit"]["auto"]
    assert store["faceit_nickname"] == "jogador1" and not store.get("faceit_key")
    assert cli.post("/api/open-faceit-history", headers=H).status_code == 200
    assert opened == ["https://www.faceit.com/pt/players/jogador1/stats/cs2"]


def test_rejects_bad_nick(tmp_path, monkeypatch):
    cli, _, _ = _client(tmp_path, monkeypatch)
    assert cli.post("/api/settings/faceit", json={"nickname": "a/../b"}, headers=H).status_code == 400
    assert cli.post("/api/open-faceit-history", headers=H).status_code == 400
