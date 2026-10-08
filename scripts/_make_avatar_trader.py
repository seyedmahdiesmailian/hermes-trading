#!/usr/bin/env python3
"""Trader+signal bot avatar: gold candlesticks + broadcast signal waves."""
import math, os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

S = 800; C = S // 2

def vgrad(top, bottom):
    img = Image.new('RGB', (S, S)); d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / (S - 1)
        d.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img

def glow(img, cx, cy, r, color, alpha=90):
    layer = Image.new('L', (S, S), 0)
    ImageDraw.Draw(layer).ellipse([cx-r, cy-r, cx+r, cy+r], fill=alpha)
    layer = layer.filter(ImageFilter.GaussianBlur(r * 0.55))
    img.paste(Image.composite(Image.new('RGB', (S, S), color), img, layer.point(lambda p: p)), (0, 0))

img = vgrad((10, 14, 26), (26, 18, 8))
glow(img, C, C + 60, 330, (255, 190, 60), 70)
d = ImageDraw.Draw(img, 'RGBA')
for i in range(0, S, 50):
    d.line([(i, 0), (i, S)], fill=(255, 255, 255, 7), width=1)
    d.line([(0, i), (S, i)], fill=(255, 255, 255, 7), width=1)
d.ellipse([C-352, C-352, C+352, C+352], outline=(212, 175, 55, 230), width=10)
d.ellipse([C-336, C-336, C+336, C+336], outline=(212, 175, 55, 70), width=3)

# ── broadcast waves (signal) top-left, gold-cyan ──
sx, sy = 205, 215
d.ellipse([sx-16, sy-16, sx+16, sy+16], fill=(120, 230, 255, 255))
for r, a in ((52, 220), (92, 150), (132, 90)):
    d.arc([sx-r, sy-r, sx+r, sy+r], start=-45, end=65, fill=(120, 230, 255, a), width=11)

# ── candlesticks ──
gold, gold_l, red = (255, 200, 70), (255, 226, 130), (235, 80, 80)
up = [1, 1, -1, 1, 1, -1, 1, 1, 1]
base = [455, 425, 470, 410, 370, 420, 345, 310, 275]
x0, step, bw = 175, 56, 30
for i, (u, b) in enumerate(zip(up, base)):
    cx = x0 + i * step
    o, c = (b + 55, b) if u == 1 else (b - 55, b)
    hi, lo = min(o, c) - 34, max(o, c) + 34
    col = gold if u == 1 else red
    d.line([(cx, hi), (cx, lo)], fill=col + (255,), width=6)
    t, bo = sorted([o, c])
    d.rounded_rectangle([cx-bw//2, t, cx+bw//2, bo], radius=6, fill=col + (255,))
pts = [(x0 + i * step, base[i] - 20) for i in range(len(base))]
for a, b in zip(pts, pts[1:]):
    d.line([a, b], fill=gold_l + (160,), width=5)
ex, ey = pts[-1]
d.polygon([(ex+34, ey-6), (ex-6, ey-30), (ex-6, ey+18)], fill=gold_l + (230,))

# ── XAUUSD plate ──
d.rounded_rectangle([C-92, 575, C+92, 655], radius=40, fill=(255, 200, 70, 255))
dd = ImageDraw.Draw(img)
fnt = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 52)
bb = dd.textbbox((0, 0), 'XAUUSD', font=fnt)
dd.text((C - (bb[2]-bb[0])//2, 615 - (bb[3]-bb[1])//2 - bb[1]), 'XAUUSD', font=fnt, fill=(15, 12, 4))

os.makedirs('assets', exist_ok=True)
img.convert('RGB').save('assets/avatar_trader.png')
print('ok')
