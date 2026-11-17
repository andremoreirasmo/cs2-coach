import gzip
import os
import time

from coach import analysis, db, demos
from coach.gsi import Tracker
from tools.simulate_gsi import payloads


def _fake_header(monkeypatch, server="Valve Counter-Strike 2 Server"):
    monkeypatch.setattr(demos, "read_header", lambda p: {"map_name": "de_mirage", "server_name": server})


def test_links_gz_demo_to_gsi_match(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    demos.set_delete_originals(False)  # aqui o mesmo arquivo é importado duas vezes
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    tr = Tracker()
    for p in payloads("x"):
        tr.handle(p)
    _fake_header(monkeypatch, "FACEIT.com register to play here")
    src = tmp_path / "1-abc.dem.gz"
    with gzip.open(src, "wb") as f:
        f.write(b"PBDEMS2\x00" + b"\x00" * 100)
    mid = demos.import_demo(src)
    assert mid == 1
    m = db.q1("SELECT * FROM matches WHERE id=1")
    assert m["status"] == "demo_pronta" and m["source"] == "faceit" and m["demo_id"]
    out = db.q1("SELECT path FROM demos WHERE id=?", m["demo_id"])["path"]
    assert open(out, "rb").read(8) == b"PBDEMS2\x00"          # foi descompactada
    assert demos.import_demo(src) is None                       # não importa duas vezes


def test_original_deleted_only_after_analysis(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    analysis.migrate()  # colunas da análise (analyzed_at)
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    _fake_header(monkeypatch, "FACEIT.com register to play here")
    src = tmp_path / "1-abc.dem.gz"
    with gzip.open(src, "wb") as f:
        f.write(b"PBDEMS2\x00" + b"\x00" * 100)
    mid = demos.import_demo(src)
    assert mid and src.exists()                                  # importar não apaga
    demos.delete_original_after_analysis(mid)
    assert src.exists()                                          # nem antes da análise dar certo
    with db.tx() as c:
        c.execute("UPDATE matches SET analyzed_at=1 WHERE id=?", (mid,))
    demos.delete_original_after_analysis(mid)
    assert not src.exists()                                      # análise ok: original apagado
    out = db.q1("SELECT path FROM demos WHERE match_id=?", mid)["path"]
    assert open(out, "rb").read(8) == b"PBDEMS2\x00"           # a cópia do app ficou
    assert demos.import_demo(src) is None                        # arquivo sumido não quebra


def test_demo_without_gsi_creates_match(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    _fake_header(monkeypatch)
    src = tmp_path / "match730_003712345678901234567_1_2.dem"
    src.write_bytes(b"PBDEMS2\x00")
    old = time.time() - 10 * 86400
    os.utime(src, (old, old))
    mid = demos.import_demo(src)
    m = db.q1("SELECT * FROM matches WHERE id=?", mid)
    assert m["source"] == "valve" and m["status"] == "demo_pronta"
    assert db.q1("SELECT sharecode_matchid FROM demos")[0] == "3712345678901234567"


def test_faceit_demo_links_by_filename(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    _fake_header(monkeypatch, "FACEIT.com register to play here")
    fid = "1-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    with db.tx() as c:  # partida criada pelo buscador da FACEIT, ainda sem demo
        c.execute("INSERT INTO matches(started_at,map,source,status,faceit_match_id) VALUES(0,'de_inferno','faceit','aguardando_demo',?)", (fid,))
    src = tmp_path / f"{fid}-1-1.dem"
    src.write_bytes(b"PBDEMS2\x00")
    assert demos.import_demo(src) == 1


def test_invalid_file_is_ignored(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    src = tmp_path / "lixo.dem"
    src.write_bytes(b"isso nao e demo")
    assert demos.import_demo(src) is None
    assert db.q1("SELECT status FROM demos")[0] == "erro"


def test_interrupted_import_is_redone_and_locked_file_retried(tmp_path, monkeypatch):
    db.use(tmp_path / "t.db")
    monkeypatch.setattr(demos, "DEMOS", tmp_path / "out")
    (tmp_path / "out").mkdir()
    _fake_header(monkeypatch, "FACEIT.com")
    src = tmp_path / "1-11111111-2222-3333-4444-555555555555-1-1.dem"
    src.write_bytes(b"PBDEMS2\x00" + b"\x00" * 50)
    # arquivo travado por outro programa: não marca erro, tenta de novo depois
    real = demos._copy_decompressed
    monkeypatch.setattr(demos, "_copy_decompressed", lambda s, d: (_ for _ in ()).throw(PermissionError(32, "em uso")))
    assert demos.import_demo(src) is None
    assert db.q1("SELECT COUNT(*) n FROM demos")["n"] == 0
    monkeypatch.setattr(demos, "_copy_decompressed", real)
    # app fechado no meio: ficou a linha da demo sem partida
    with db.tx() as c:
        c.execute("INSERT INTO demos(original, path, added_at, status) VALUES(?, 'x', 0, 'nova')", (demos.signature(src),))
    assert demos.import_demo(src) == 1
    assert db.q1("SELECT COUNT(*) n FROM demos WHERE match_id=1")["n"] == 1
