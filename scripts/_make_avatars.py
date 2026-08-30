#!/usr/bin/env python3
"""Generate two Telegram profile pictures (800x800) with PIL primitives."""
import math, random
from PIL import Image, ImageDraw, ImageFilter

S = 800
C = S // 2

def vgrad(top, bottom):
    img = Image.new('RGB', (S, S))
    d = ImageDraw.Draw(img)
    for y in range(S):
        t = y / (S - 1)
        d.line([(0, y), (S, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img

def glow(img, cx, cy, r, color, alpha=90):
    layer = Image.new('L', (S, S), 0)
    ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r], fill=alpha)
    layer = layer.filter(ImageFilter.GaussianBlur(r * 0.55))
    tint = Image.new('RGB', (S, S), color)
    img.paste(Image.composite(tint, img, layer.point(lambda p: p)), (0, 0))

def ring(img, r, color, w):
    d = ImageDraw.Draw(img, 'RGBA')
    d.ellipse([C - r, C - r, C + r, C + r], outline=color, width=w)

# ────────────────────────── TRADER / SIGNAL BOT ──────────────────────────
def trader():
    img = vgrad((10, 14, 26), (24, 18, 8))
    glow(img, C, C + 60, 330, (255, 190, 60), 70)
    # subtle grid
    d = ImageDraw.Draw(img, 'RGBA')
    for i in range(0, S, 50):
        d.line([(i, 0), (i, S)], fill=(255, 255, 255, 7), width=1)
        d.line([(0, i), (S, i)], fill=(255, 255, 255, 7), width=1)
    ring(img, 352, (212, 175, 55, 230), 10)
    ring(img, 336, (212, 175, 55, 70), 3)

    d = ImageDraw.Draw(img, 'RGBA')
    gold, gold_l, red = (255, 200, 70), (255, 226, 130), (235, 80, 80)
    up = [1, 1, -1, 1, 1, -1, 1, 1, 1]
    base = [430, 400, 445, 385, 345, 395, 320, 285, 250]
    x0, step, bw = 175, 56, 30
    prev_close = None
    for i, (u, b) in enumerate(zip(up, base)):
        cx = x0 + i * step
        o, c = (b + 55, b) if u == 1 else (b - 55, b)
        hi, lo = min(o, c) - 34, max(o, c) + 34
        col = gold if u == 1 else red
        d.line([(cx, hi), (cx, lo)], fill=col + (255,), width=6)
        top_y, bot_y = sorted([o, c])
        d.rounded_rectangle([cx - bw // 2, top_y, cx + bw // 2, bot_y],
                            radius=6, fill=col + (255,))
        prev_close = c
    # trend line through candle tops
    pts = [(x0 + i * step, base[i] - 20) for i in range(len(base))]
    for a, b in zip(pts, pts[1:]):
        d.line([a, b], fill=gold_l + (160,), width=5)
    # arrow head
    ex, ey = pts[-1]
    d.polygon([(ex + 34, ey - 6), (ex - 6, ey - 30), (ex - 6, ey + 18)], fill=gold_l + (230,))
    # XAU tag
    d.rounded_rectangle([C - 92, 560, C + 92, 640], radius=40, fill=(255, 200, 70, 255))
    dd = ImageDraw.Draw(img)
    from PIL import ImageFont
    fnt = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 52)
    t = 'XAUUSD'
    bb = dd.textbbox((0, 0), t, font=fnt)
    dd.text((C - (bb[2]-bb[0])//2, 600 - (bb[3]-bb[1])//2 - bb[1]), t,
            font=fnt, fill=(15, 12, 4))
    return img

# ────────────────────────── REPORT / OPS BOT ──────────────────────────
def reporter():
    random.seed(7)
    img = vgrad((8, 16, 30), (6, 34, 40))
    glow(img, C, C, 320, (0, 220, 255), 55)
    d = ImageDraw.Draw(img, 'RGBA')
    # hex grid, faint
    for yy in range(60, S, 90):
        for xx in range(60, S, 90):
            ox = 45 if (yy // 90) % 2 else 0
            p = [(xx+ox+30, yy), (xx+ox+60, yy+18), (xx+ox+60, yy+50),
                 (xx+ox+30, yy+68), (xx, yy+50), (xx, yy+18)]
            d.polygon(p, outline=(120, 220, 255, 14))
    ring(img, 352, (0, 210, 255, 220), 10)
    ring(img, 336, (0, 210, 255, 60), 3)

    # dashboard arc gauge (270deg)
    gr = 210
    bbox = [C - gr, C - gr + 20, C + gr, C + gr + 20]
    d.arc(bbox, start=135, end=405, fill=(40, 70, 100, 255), width=34)
    d.arc(bbox, start=135, end=310, fill=(0, 225, 255, 255), width=34)
    d.arc(bbox, start=310, end=355, fill=(255, 190, 60, 255), width=34)
    d.arc(bbox, start=355, end=405, fill=(240, 80, 80, 255), width=34)
    # needle
    ang = math.radians(310)
    nx, ny = C + (gr - 8) * math.cos(ang), C + 20 + (gr - 8) * math.sin(ang)
    d.line([(C, C + 20), (nx, ny)], fill=(235, 245, 255, 255), width=10)
    d.ellipse([C - 22, C - 2, C + 22, C + 42], fill=(10, 20, 34, 255),
              outline=(0, 225, 255, 255), width=5)

    # mini bars bottom-left + pulse line bottom-right
    for i, h in enumerate((26, 48, 34, 62)):
        x = 150 + i * 34
        d.rounded_rectangle([x, 640 - h, x + 22, 640], radius=6, fill=(0, 225, 255, 200))
    pulse = [(470, 630), (505, 630), (522, 590), (545, 655), (565, 610), (585, 630), (640, 630)]
    for a, b in zip(pulse, pulse[1:]):
        d.line([a, b], fill=(80, 255, 190, 230), width=7)
    # status dot
    d.ellipse([600, 150, 660, 210], fill=(60, 255, 140, 255))
    glow(img, 630, 180, 60, (60, 255, 140), 80)
    return img

import os
os.makedirs('/home/ai/hermes-trading/assets', exist_ok=True)
trader().convert('RGB').save('/home/ai/hermes-trading/assets/avatar_trader.png')
reporter().convert('RGB').save('/home/ai/hermes-trading/assets/avatar_report.png')
print('done')
