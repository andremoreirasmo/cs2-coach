from coach import moments


def test_half_ends_include_overtime_halves():
    ends = moments._half_ends(46)
    assert {12, 24, 27, 30, 33, 36, 39, 42, 45} <= ends
    assert 25 not in ends and 28 not in ends


def test_money_format_brazil():
    assert moments._brl(11350) == "$11.350"
    assert moments._brl(800) == "$800"
