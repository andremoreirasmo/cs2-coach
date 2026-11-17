from fastapi.testclient import TestClient

from coach import analysis, db, overview
from coach.gsi import Tracker
from coach.server import create_app
from coach.services import Analyzer

ME, EN = "76561198000000001", "76561198000000002"


def _seed(tmp_path):
    db.use(tmp_path / "t.db")
    analysis.migrate()
    db.kv_set("steamid", ME)
    with db.tx() as c:
        c.execute("""INSERT INTO matches(id, started_at, map, source, status, team_a, team_b, score_a, score_b, rounds_total,
                     analyzed_at, my_steamid) VALUES(1,1,'de_dust2','faceit','analisada','A','B',13,10,23,1,?)""", (ME,))
        for sid, name, team in ((ME, "Eu", "A"), (EN, "Ele", "B")):
            c.execute("INSERT INTO demo_players VALUES(1,?,?,?,'CT',10,12,2,1500,68,40,61,2,4,1,3,50,23,0.83,5,4,1,0,1,1,15000,10)",
                      (sid, name, team))
        c.execute("INSERT INTO demo_rounds VALUES(1,1,'T','ct_killed','B','CT',0,1,100,900,4000,4000,'pistol','pistol')")
        c.execute("INSERT INTO demo_player_rounds VALUES(1,1,?,'CT',800,0,0,1,0,40,0)", (ME,))
        c.execute("""INSERT INTO demo_kills VALUES(1,1,500,12.5,?,?,'','ak47',1,'T','CT',0,0,0,0,1,0,0,0,0,900,4,5,1500,0,
                     0,0,1,0,0,0,0,'Banana','BombsiteB','AK-47',2,165,13,2)""", (EN, ME))


def test_overview_stats_and_sources(tmp_path):
    _seed(tmp_path)
    st = TestClient(create_app(Tracker())).get("/api/overview").json()
    assert st["total"]["partidas"] == 1 and st["total"]["kd"] == round(10 / 12, 2)
    assert st["fontes"]["faceit"]["total"]["partidas"] == 1 and st["fontes"]["valve"]["total"] is None
    assert st["mortes"]["lugares"][0]["lugar"].startswith("Bomb B") and st["mortes"]["abertura"] == 100
    assert st["lados"]["CT"]["rounds"] == 1


def test_queue_dedupes():
    a = Analyzer(busy=lambda: False)
    a.submit(2)
    a.submit(2)
    a.submit(3)
    order = [a.q.get() for _ in range(a.q.qsize())]
    assert [(k, m) for k, _, m in order] == [(0, 2), (0, 3)]
    assert a.progress()["analise"]["total"] == 2


def test_callouts_in_portuguese():
    from coach.callouts import br
    assert br("de_dust2", "ShortStairs") == "Escada do short"
    assert br("de_mirage", "SnipersNest") == "Janela"
    assert br("de_overpass", "UpperPark") == "Park de cima"
    assert br("de_dust2", None) is None
