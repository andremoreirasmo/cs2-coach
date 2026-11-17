import gzip

from fastapi.testclient import TestClient

from coach import db, demos, demos_api
from coach.gsi import Tracker
from coach.server import create_app

H = {"X-Coach": "1"}


def _client(tmp_path, monkeypatch, picked=None):
    db.use(tmp_path / "t.db")
    demos.set_delete_originals(False)  # o teste escolhe o mesmo arquivo duas vezes
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    monkeypatch.setattr(demos_api, "INBOX", tmp_path)
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(demos, "read_header", lambda p: {"map_name": "de_inferno", "server_name": "FACEIT.com"})
    submitted = []
    app = create_app(Tracker(), pick_files=(lambda: picked) if picked is not None else None, on_demo=submitted.append)
    return TestClient(app), submitted


def test_upload_gz_demo(tmp_path, monkeypatch):
    cli, sub = _client(tmp_path, monkeypatch)
    body = gzip.compress(b"PBDEMS2\x00" + b"\x00" * 50)
    r = cli.post("/api/demos/upload", content=body, headers={**H, "X-Filename": "partida.dem.gz"})
    res = r.json()["results"][0]
    assert res["ok"] and res["match_id"] == 1 and sub == [1]


def test_pick_imports_and_detects_duplicates(tmp_path, monkeypatch):
    f = tmp_path / "x.dem"
    f.write_bytes(b"PBDEMS2\x00")
    cli, sub = _client(tmp_path, monkeypatch, picked=[str(f)])
    first = cli.post("/api/demos/pick", json={}, headers=H).json()["results"][0]
    again = cli.post("/api/demos/pick", json={}, headers=H).json()["results"][0]
    assert first["ok"] and again["msg"] == "já estava importada" and sub == [1]


def test_rejects_wrong_extension_and_no_window(tmp_path, monkeypatch):
    cli, _ = _client(tmp_path, monkeypatch)
    assert cli.post("/api/demos/upload", content=b"x", headers={**H, "X-Filename": "foto.png"}).status_code == 400
    assert cli.post("/api/demos/pick", json={}, headers=H).status_code == 501
