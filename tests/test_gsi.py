from fastapi.testclient import TestClient

from coach import db
from coach.config import gsi_token
from coach.gsi import Tracker
from coach.server import create_app
from tools.simulate_gsi import payloads


def setup_function(_):
    pass


def _run(tmp_path):
    db.use(tmp_path / "t.db")
    ended = []
    tr = Tracker(on_match_end=ended.append)
    for p in payloads("x"):
        tr.handle(p)
    return tr, ended


def test_full_match(tmp_path):
    tr, ended = _run(tmp_path)
    assert ended == [1] and not tr.in_match
    m = db.q1("SELECT * FROM matches WHERE id=1")
    # 22 rounds: CT ganhou 15? conta pelo roteiro
    script = "CCCTCCTCCTCT" "TCCTCCCCTC"
    ct, t = script.count("C"), script.count("T")
    assert (m["score_ct"], m["score_t"]) == (ct, t)
    assert m["my_team_final"] == "T"
    assert (m["my_score"], m["enemy_score"]) == (t, ct)
    assert m["result"] == ("vitoria" if t > ct else "derrota")
    assert m["status"] == "terminada"

    rounds = db.q("SELECT * FROM rounds WHERE match_id=1 ORDER BY round_num")
    assert [r["round_num"] for r in rounds] == list(range(1, 23))
    assert rounds[0]["my_team"] == "CT" and rounds[12]["my_team"] == "T"   # troca de lado
    assert all(r["winner"] == ("CT" if c == "C" else "T") for r, c in zip(rounds, script))
    assert sum(r["died"] for r in rounds) == m["deaths"]                    # mortes por round batem
    assert sum(r["kills"] for r in rounds) == m["kills"]


def test_ignores_casual_and_menu(tmp_path):
    db.use(tmp_path / "t.db")
    tr = Tracker()
    tr.handle({"provider": {"steamid": "1"}})
    tr.handle({"provider": {"steamid": "1"}, "map": {"mode": "casual", "name": "de_dust2", "phase": "live"}})
    assert tr.match_id is None
    assert db.q("SELECT * FROM matches") == []


def test_busy_in_any_map(tmp_path):
    db.use(tmp_path / "t.db")
    tr = Tracker()
    assert not tr.busy
    tr.handle({"provider": {"steamid": "1"}, "map": {"mode": "deathmatch", "name": "de_mirage", "phase": "live"}})
    assert tr.busy and not tr.in_match      # DM: não é partida rastreada, mas não pode pesar no jogo
    tr.handle({"provider": {"steamid": "1"}})  # voltou ao menu
    assert not tr.busy


def test_settings_blocks_other_sites(tmp_path):
    db.use(tmp_path / "t.db")
    cli = TestClient(create_app(Tracker()))
    assert cli.post("/api/settings/pausar", json={"on": True}).status_code == 403            # sem cabeçalho do app
    assert cli.post("/api/settings/pausar", json={"on": True},
                    headers={"X-Coach": "1", "Origin": "https://site-malicioso.com"}).status_code == 403


def test_server_rejects_wrong_token(tmp_path):
    db.use(tmp_path / "t.db")
    cli = TestClient(create_app(Tracker()))
    assert cli.post("/gsi", json={"auth": {"token": "errado"}}).status_code == 401
    assert cli.post("/gsi", json={"auth": {"token": gsi_token()}}).status_code == 200
