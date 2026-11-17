"""Extrai as imagens de radar e os dados de overview dos arquivos do próprio CS2.

Só LÊ o pak01_dir.vpk do jogo (nada é alterado). Para cada mapa gera:
  data/radars/<mapa>.png       imagem 1024x1024
  data/radars/overviews.json   pos_x, pos_y, scale (+ andares de baixo: nuke, vertigo...)

Conversão de coordenadas do jogo para pixel do radar:
  px = (x - pos_x) / scale
  py = (pos_y - y) / scale
"""
from __future__ import annotations

import json
import logging
import re
import struct

import lz4.block
from PIL import Image

from .config import DATA, settings

log = logging.getLogger("coach.radar")
OUT = DATA / "radars"
OVERVIEWS = OUT / "overviews.json"
FMT_BGRA8888, FMT_RGBA8888 = 28, 4
FORMAT_V = 2  # muda quando o conteúdo do overviews.json muda


def _vpk():
    import vpk
    cs = settings.cs2_dir
    if not cs:
        raise RuntimeError("CS2 não encontrado")
    return vpk.open(str(cs / "game" / "csgo" / "pak01_dir.vpk"))


def decode_vtex(b: bytes) -> Image.Image:
    """Lê uma textura Source 2 (.vtex_c) sem compressão de bloco (BGRA/RGBA, LZ4 opcional)."""
    _, _, _, boff, bcnt = struct.unpack_from("<IHHII", b, 0)
    pos, blocks = 8 + boff, {}
    for _ in range(bcnt):
        typ = b[pos:pos + 4].decode("ascii", "replace")
        off, sz = struct.unpack_from("<II", b, pos + 4)
        blocks[typ] = (pos + 4 + off, sz)
        pos += 12
    do, ds = blocks["DATA"]
    w, h, _, fmt, mips = struct.unpack_from("<HHHBB", b, do + 20)
    if fmt not in (FMT_BGRA8888, FMT_RGBA8888):
        raise ValueError(f"formato de textura não suportado: {fmt}")
    raw_len = w * h * 4
    data = b[do + ds:]
    if len(data) < raw_len:  # compactado; o mip 0 (maior) é o último
        out = lz4.block.decompress(data, uncompressed_size=sum((w >> i) * (h >> i) * 4 for i in range(mips)))
        pix = out[-raw_len:]
    else:
        pix = data[-raw_len:]
    return Image.frombytes("RGBA", (w, h), pix, "raw", "BGRA" if fmt == FMT_BGRA8888 else "RGBA")


def _parse_overview(txt: str) -> dict:
    def num(key, s=txt):
        m = re.search(rf'"{key}"\s+"(-?[\d.]+)"', s, re.I)
        return float(m.group(1)) if m else None

    info = {"pos_x": num("pos_x"), "pos_y": num("pos_y"), "scale": num("scale")}
    for site in ("A", "B"):  # centro do bombsite (fração da imagem -> coordenada do jogo)
        bx, by = num(f"bomb{site}_x"), num(f"bomb{site}_y")
        if None not in (bx, by, info["pos_x"], info["scale"]):
            info[f"bomb{site}"] = [info["pos_x"] + bx * 1024 * info["scale"], info["pos_y"] - by * 1024 * info["scale"]]
    vs = re.search(r'"verticalsections"\s*\{(.*)\}', txt, re.S | re.I)
    if vs:
        secs = []
        for name, body in re.findall(r'"(\w+)"\s*\{([^{}]*)\}', vs.group(1)):
            secs.append({"name": name, "z_max": num("AltitudeMax", body), "z_min": num("AltitudeMin", body)})
        info["sections"] = secs
    return info


def extract_all(force: bool = False) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    if OVERVIEWS.exists() and not force:
        cached = json.loads(OVERVIEWS.read_text())
        if cached.get("_v") == FORMAT_V:
            return cached
    pak = _vpk()
    files = set(pak)
    result: dict = {"_v": FORMAT_V}
    for f in sorted(files):
        m = re.match(r"panorama/images/overheadmaps/(\w+)_radar_psd\.vtex_c$", f)
        if not m:
            continue
        name = m.group(1)
        try:
            decode_vtex(pak[f].read()).save(OUT / f"{name}.png", optimize=True)
        except Exception as e:
            log.warning("radar %s: %s", name, e)
            continue
        base = re.sub(r"_(lower|upper|night|v\d)$", "", name)
        ov = f"resource/overviews/{base}.txt"
        if ov in files:
            info = _parse_overview(pak[ov].read().decode("utf-8", "replace"))
            info["image"] = f"{name}.png"
            result[name] = info
    OVERVIEWS.write_text(json.dumps(result, indent=1))
    log.info("Radares extraídos: %d mapas", len(result))
    return result


SHOTS = OUT / "shots"
SHOT_RE = re.compile(r"panorama/images/map_icons/screenshots/720p/(\w+?)_png\.vtex_c$")


def extract_shots(force: bool = False) -> int:
    """Foto de cada mapa (a mesma da tela de seleção de mapas do jogo) -> data/radars/shots/<mapa>.jpg.
    A textura traz um PNG dentro; é só achar e salvar menor."""
    import io

    SHOTS.mkdir(parents=True, exist_ok=True)
    pak = _vpk()
    n = 0
    for path in pak:
        m = SHOT_RE.search(path)
        if not m:
            continue
        name = m.group(1)
        dst = SHOTS / f"{name}.jpg"
        if dst.exists() and not force:
            continue
        try:
            b = pak[path].read()
            i = b.find(b"\x89PNG")
            if i < 0:
                continue
            im = Image.open(io.BytesIO(b[i:])).convert("RGB")
            im.thumbnail((640, 360))
            im.save(dst, quality=82)
            n += 1
        except Exception:
            log.warning("Não deu para extrair a foto de %s", name)
    if n:
        log.info("Fotos de mapas extraídas: %d", n)
    return n


def overview(map_name: str) -> dict | None:
    data = extract_all()
    ov = data.get(map_name)
    if not ov:
        return None
    lower = data.get(f"{map_name}_lower")
    if lower and map_name in LOWER_Z:
        ov = {**ov, "lower": {"image": lower["image"], "z_max": LOWER_Z[map_name]}}
    return ov


# abaixo dessa altura (Z) o jogador está no andar de baixo
LOWER_Z = {"de_nuke": -495, "de_vertigo": 11700, "de_train": -50}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for k, v in extract_all(force=True).items():
        print(k, v)
