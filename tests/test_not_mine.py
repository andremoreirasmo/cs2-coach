from coach import analysis, db, demos


def test_demo_without_you_is_ignored(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    analysis.migrate()
    db.kv_set("steamid", "76561198000000001")
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    monkeypatch.setattr(demos, "read_header", lambda p: {"map_name": "de_mirage", "server_name": "HLTV"})
    monkeypatch.setattr(demos, "_has_me", lambda p: False)
    src = tmp_path / "vitality-vs-mouz-m1-mirage.dem"
    src.write_bytes(b"PBDEMS2\x00" + b"\x00" * 100)
    assert demos.import_demo(src) is None
    assert not db.q("SELECT 1 FROM matches")
    assert db.q1("SELECT status FROM demos")["status"] == "nao_sua"
    assert not list((tmp_path / "out").iterdir())  # a cópia não fica
    assert demos.import_demo(src) is None  # da próxima vez nem copia
