from coach import duels


def test_tipo():
    assert duels.tipo(165, 13, 2) == "entrou"      # você correndo, ele parado mirando
    assert duels.tipo(165, 232, 2) == "correndo"   # os dois rápidos, você correndo
    assert duels.tipo(80, 120, 5) == "movimento"
    assert duels.tipo(10, 231, 14) == "peek"       # você parado, ele veio
    assert duels.tipo(15, 13, 0) == "mira"
    assert duels.tipo(0, 0, 60) == "lado"
    assert duels.tipo(113, 31, 137) == "costas"
    assert duels.tipo(None, 10, 3) is None
