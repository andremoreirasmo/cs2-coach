import pandas as pd

from coach import aim

SID = "76561198000000001"
T = 1000


class FakeParser:
    """Jogador anda para a direita (tecla RIGHT) e freia; speeds = velocidade por tick até o tiro e depois."""

    def __init__(self, speeds, counter_from=None, counter_to=None, release_at=None):
        rows, x = [], 0.0
        for i, t in enumerate(range(T - aim.STRAFE_BEFORE, T + aim.STRAFE_AFTER + 1)):
            x += speeds[i] / aim.TICKRATE
            rel = t - T
            right = release_at is None or rel < release_at
            left = counter_from is not None and counter_from <= rel < counter_to
            rows.append({"tick": t, "steamid": int(SID), "X": x, "Y": 0.0, "FORWARD": False, "BACK": False,
                         "LEFT": left, "RIGHT": right and not left})
        self.df = pd.DataFrame(rows)

    def parse_ticks(self, props, ticks=None):
        return self.df[self.df["tick"].isin(ticks)]


def _shot():
    # [rn, tick, sid, w, speed, moving, air, crouch, scoped, burst, ...]
    return [1, T, SID, "ak47", 0, 0, 0, 0, 0, 1, 0, 0, 0, 0.0, 0.0]


def _run(**kw):
    return aim._strafes(FakeParser(**kw), [_shot()])[(T, SID)][0]


N = aim.STRAFE_BEFORE + aim.STRAFE_AFTER + 1


def test_counter_strafe_cases():
    run = [215] * N
    # freou com a tecla contrária e já estava parado no tiro
    stop = [215] * 16 + [150, 80, 20] + [0] * (N - 19)
    assert _run(speeds=stop, counter_from=-8, counter_to=-5, release_at=-8) == "ok_cs"
    # atirou ainda freando (passou de 34% da velocidade da AK)
    late = [215] * 20 + [180, 150, 120, 100, 90] + [30] * (N - 25)
    assert _run(speeds=late, counter_from=-4, counter_to=0, release_at=-4) == "cedo"
    # não freou
    assert _run(speeds=run) == "andando"
    # já estava parado
    assert _run(speeds=[0] * N) == "parado"
    # segurou a tecla contrária e voltou a andar para o outro lado
    back = [215] * 14 + [120, 40] + [-40, -90, -120, -140, -150, -150, -150, -150, -150] + [-150] * (N - 25)
    assert _run(speeds=back, counter_from=-10, counter_to=5, release_at=-10) == "demais"
