"""Gera assets/icon.ico e assets/icon.png (logo do app)."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)

S = 512
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
# fundo arredondado com degradê âmbar -> laranja
grad = Image.new("RGBA", (S, S))
gd = ImageDraw.Draw(grad)
for y in range(S):
    t = y / S
    gd.line([(0, y), (S, y)], fill=(int(244 - 20 * t), int(178 - 66 * t), int(62 - 20 * t), 255))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([16, 16, S - 16, S - 16], radius=110, fill=255)
img.paste(grad, (0, 0), mask)

d = ImageDraw.Draw(img)
ink = (21, 16, 10, 255)
c, r, w = S // 2, 150, 38
d.arc([c - r, c - r, c + r, c + r], 35, 325, fill=ink, width=w)       # "C" / mira aberta
for (x0, y0, x1, y1) in [(c - 22, 70, c + 22, 150), (c - 22, S - 150, c + 22, S - 70), (70, c - 22, 150, c + 22)]:
    d.rounded_rectangle([x0, y0, x1, y1], radius=12, fill=ink)        # traços da mira
d.ellipse([c - 34, c - 34, c + 34, c + 34], fill=ink)                 # ponto central

img.save(OUT / "icon.png")
img.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("ok", OUT)
