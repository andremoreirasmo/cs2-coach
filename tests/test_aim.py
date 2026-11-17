from coach import aim


def test_verdicts_flag_moving_and_spray():
    me = {"andando": 35, "prec_andando": 8, "prec_parado": 22, "primeiro": 30, "lobby": None,
          "spray_meio": 10, "spray_fim": 3, "hs": 30, "ajuste": 2.0, "rajada_longa": 20, "no_ar": 0.5}
    lob = {"andando": 24, "prec_andando": 10, "prec_parado": 18, "primeiro": 25,
           "spray_meio": 16, "spray_fim": 6, "hs": 20, "ajuste": 1.8, "rajada_longa": 20, "no_ar": 1}
    v = aim._verdicts(me, lob)
    bad = {x["titulo"] for x in v if x["tipo"] == "melhorar"}
    good = {x["titulo"] for x in v if x["tipo"] == "bom"}
    assert "Você atira andando" in bad and "O spray perde controle" in bad
    assert "Primeira bala precisa" in good and "Mira na cabeça" in good
    assert "Mira chega longe do inimigo" not in bad  # diferença pequena (0,2°) não conta


def test_summary_counts():
    # (weapon, moving, air, burst, hit, head, flick, scoped)
    rows = [("ak47", 0, 0, 1, 1, 1, 1.0, 0), ("ak47", 0, 0, 2, 0, 0, None, 0), ("ak47", 1, 0, 1, 0, 0, None, 0),
            ("ak47", 0, 0, 5, 1, 0, None, 0)]
    s = aim._summary(rows)
    assert s["tiros"] == 4 and s["precisao"] == 50.0 and s["hs"] == 50.0
    assert s["primeiro"] == 50.0 and s["andando"] == 25.0 and s["spray_meio"] == 100.0
