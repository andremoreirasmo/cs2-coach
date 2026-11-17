from coach.sharecode import decode


def test_decode_known_code():
    d = decode("CSGO-GADqf-jjyJ8-cSP2r-smZRo-TO2xK")
    assert d == {"match_id": 3230642215713767580, "outcome_id": 3230647599455273103, "token": 55788}
