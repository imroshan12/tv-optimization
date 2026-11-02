#!/usr/bin/env python3
"""Draw one original character per Home tile as a dark, rim-lit 1280x720 JPEG.

Usage: make_avatars.py <output dir>
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

W, H = 1280, 720
SS = 2


def rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def smoke(seed, scale=90, contrast=1.6):
    """Soft fractal noise in 0..1: the haze behind every figure."""
    rng = np.random.default_rng(seed)
    out = np.zeros((H, W), np.float32)
    amp = 1.0
    for octave in range(4):
        step = max(2, scale >> octave)
        small = rng.random((H // step + 2, W // step + 2)) * 255
        layer = Image.fromarray(small.astype(np.uint8)).resize((W, H), Image.BICUBIC)
        out += amp * np.asarray(layer, np.float32) / 255
        amp *= 0.5
    out = (out - out.min()) / (out.max() - out.min())
    return np.clip((out - 0.5) * contrast + 0.5, 0, 1)


def radial(cx, cy, rx, ry):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
    return np.clip(1 - d, 0, 1) ** 1.6


def backdrop(base, accent, second, seed, cx=880, cy=300):
    haze = smoke(seed)
    light = radial(cx, cy, 620, 480)
    wash = radial(cx - 520, cy + 200, 560, 400)
    img = np.zeros((H, W, 3), np.float32)
    for i in range(3):
        img[..., i] = (base[i]
                       + accent[i] * light * (0.42 + 0.58 * haze) * 0.85
                       + second[i] * wash * haze * 0.30)
    return img


class Figure:
    """A silhouette drawn on a supersampled mask, with emissive details kept apart."""

    def __init__(self):
        self.mask = Image.new("L", (W * SS, H * SS), 0)
        self.d = ImageDraw.Draw(self.mask)
        self.glow = Image.new("RGB", (W * SS, H * SS), (0, 0, 0))
        self.g = ImageDraw.Draw(self.glow)

    def poly(self, pts, fill=255):
        self.d.polygon([(x * SS, y * SS) for x, y in pts], fill=fill)

    def disc(self, cx, cy, rx, ry=None, fill=255):
        ry = rx if ry is None else ry
        self.d.ellipse([(cx - rx) * SS, (cy - ry) * SS, (cx + rx) * SS, (cy + ry) * SS], fill=fill)

    def limb(self, pts, width, end=None, fill=255):
        """A tapered chain of capsules: arms, legs, capes."""
        end = width if end is None else end
        n = len(pts) - 1
        for i in range(n):
            (x0, y0), (x1, y1) = pts[i], pts[i + 1]
            w0 = width + (end - width) * i / n
            w1 = width + (end - width) * (i + 1) / n
            for t in np.linspace(0, 1, 26):
                w = w0 + (w1 - w0) * t
                self.disc(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, w / 2, fill=fill)

    def lit_line(self, pts, color, width=3):
        self.g.line([(x * SS, y * SS) for x, y in pts], fill=color, width=width * SS, joint="curve")

    def lit_disc(self, cx, cy, r, color):
        self.g.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], fill=color)

    def lit_poly(self, pts, color):
        self.g.polygon([(x * SS, y * SS) for x, y in pts], fill=color)

    def lit_ring(self, cx, cy, r, color, width=4):
        self.g.ellipse([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], outline=color, width=width * SS)


def compose(fig, base, accent, second, seed, fg=None, behind=None, cx=880, cy=300, light_dir=(-5, -4)):
    img = backdrop(base, accent, second, seed, cx, cy)
    if behind is not None:
        img = np.clip(img + behind, 0, 255)
    mask_small = fig.mask.resize((W, H), Image.LANCZOS)
    m = np.asarray(mask_small, np.float32) / 255

    # Halo behind the figure, in the accent colour.
    halo = np.asarray(mask_small.filter(ImageFilter.GaussianBlur(46)), np.float32) / 255
    for i in range(3):
        img[..., i] += accent[i] * halo * 0.40

    # The body: near black, a touch lighter toward the lit side.
    shade = np.asarray(ImageChops.offset(mask_small, 28, 22).filter(ImageFilter.GaussianBlur(24)), np.float32) / 255
    for i in range(3):
        body = base[i] * 0.35 + accent[i] * 0.10 * (1 - shade) + 5
        img[..., i] = img[..., i] * (1 - m) + body * m

    # Rim light: where the mask, shifted toward the light, leaves an edge.
    shifted = ImageChops.offset(mask_small, -light_dir[0], -light_dir[1])
    rim = ImageChops.subtract(mask_small, shifted).filter(ImageFilter.GaussianBlur(1.1))
    r = np.asarray(rim, np.float32) / 255
    wide = np.asarray(rim.filter(ImageFilter.GaussianBlur(7)), np.float32) / 255
    for i in range(3):
        img[..., i] += (accent[i] * 0.55 + 200) * r * 0.95 + accent[i] * wide * 0.9

    # Lit details and their bloom.
    glow_small = fig.glow.resize((W, H), Image.LANCZOS)
    g = np.asarray(glow_small, np.float32)
    bloom = np.asarray(glow_small.filter(ImageFilter.GaussianBlur(16)), np.float32)
    img = img + g + bloom * 1.25

    if fg is not None:
        img = fg(img)

    # Keep the clock corner and the row of tiles readable: darken left, top corner and floor.
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    floor = np.clip((y - 420) / 260, 0, 1) ** 1.25
    left = np.clip((520 - x) / 520, 0, 1) ** 1.1
    top = np.clip((130 - y) / 130, 0, 1) * 0.55
    keep = (1 - floor * 0.9) * (1 - left * 0.62) * (1 - top)
    img = img * keep[..., None]

    # A little grain hides banding once this is decoded in 16-bit colour.
    rng = np.random.default_rng(seed + 7)
    img += rng.normal(0, 2.2, (H, W, 1))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def stars(seed, n=200, cut=720):
    rng = np.random.default_rng(seed)
    a = np.zeros((H, W, 3), np.float32)
    for _ in range(n):
        x, y = rng.integers(0, W), rng.integers(0, cut)
        a[y, x] = rng.random() * 180 + 60
    pil = Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    return np.asarray(pil, np.float32) * 1.8


def beams(sources, spread, color, strength=0.26):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    out = np.zeros((H, W, 3), np.float32)
    for sx, sy, aim in sources:
        ang = np.arctan2(y - sy, x - sx)
        cone = np.clip(1 - np.abs(ang - aim) / spread, 0, 1) ** 2.2
        fall = np.clip(1 - np.hypot(x - sx, y - sy) / 900, 0, 1)
        for i in range(3):
            out[..., i] += color[i] * cone * fall * strength
    return out


def hooded_knight():
    """Netflix: a hooded figure with a long cape, lit in red."""
    f = Figure()
    cx = 880
    f.poly([(cx - 140, 690), (cx - 112, 400), (cx - 92, 262), (cx - 54, 216), (cx + 56, 216), (cx + 94, 262),
            (cx + 118, 400), (cx + 164, 690)])
    f.poly([(cx - 52, 222), (cx - 58, 150), (cx - 26, 92), (cx + 6, 78), (cx + 34, 96), (cx + 58, 150), (cx + 54, 222)])
    f.poly([(cx - 150, 690), (cx - 196, 560), (cx - 128, 330), (cx - 90, 280), (cx - 80, 690)])
    f.limb([(cx + 88, 268), (cx + 136, 370), (cx + 124, 448)], 46, 30)
    f.limb([(cx + 124, 448), (cx + 124, 660)], 12, 10)
    f.lit_line([(cx + 124, 440), (cx + 124, 668)], (255, 60, 50), 3)
    f.lit_poly([(cx - 18, 148), (cx + 26, 148), (cx + 20, 158), (cx - 12, 158)], (255, 50, 40))
    return compose(f, (9, 4, 7), (205, 18, 30), (120, 12, 40), 11)


def creator():
    """YouTube: a creator in headphones holding a camera, before a glowing play sign."""
    f = Figure()
    cx = 900
    f.limb([(cx - 34, 468), (cx - 52, 690)], 66, 56)
    f.limb([(cx + 34, 468), (cx + 58, 690)], 66, 56)
    f.poly([(cx - 96, 498), (cx - 104, 290), (cx - 68, 240), (cx + 68, 240), (cx + 104, 290), (cx + 96, 498)])
    f.limb([(cx, 240), (cx, 204)], 42)
    f.disc(cx, 160, 56, 62)
    f.d.arc([(cx - 72) * SS, (cx * 0 + 88) * SS, (cx + 72) * SS, 232 * SS], 180, 360, fill=255, width=14 * SS)
    f.disc(cx - 66, 164, 22, 32)
    f.disc(cx + 66, 164, 22, 32)
    f.limb([(cx - 90, 288), (cx - 146, 372), (cx - 214, 300)], 42, 32)
    f.limb([(cx + 90, 288), (cx + 118, 410), (cx + 60, 462)], 42, 32)
    f.poly([(cx - 288, 256), (cx - 196, 256), (cx - 196, 322), (cx - 288, 322)])
    f.poly([(cx - 310, 270), (cx - 288, 276), (cx - 288, 306), (cx - 310, 312)])
    f.lit_disc(cx - 318, 292, 7, (255, 240, 240))
    f.lit_disc(cx - 210, 268, 4, (255, 40, 40))
    behind = np.zeros((H, W, 3), np.float32)
    sign = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(sign)
    d.rounded_rectangle([cx - 262, 126, cx + 176, 404], 56, outline=255, width=7)
    d.polygon([(cx + 108, 176), (cx + 108, 238), (cx + 158, 207)], outline=255, width=6)
    arr = np.asarray(sign, np.float32) / 255
    wide = np.asarray(sign.filter(ImageFilter.GaussianBlur(16)), np.float32) / 255
    behind[..., 0] = arr * 225 + wide * 190
    behind[..., 1] = arr * 45 + wide * 14
    behind[..., 2] = arr * 40 + wide * 16
    return compose(f, (8, 5, 8), (205, 25, 30), (70, 30, 90), 22, behind=behind, cx=900, cy=220)


def voyager():
    """Prime Video: a caped voyager with a glowing staff before a blue city."""
    f = Figure()
    cx = 870
    rng = np.random.default_rng(5)
    city = np.zeros((H, W, 3), np.float32)
    skyline = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(skyline)
    x = 420
    while x < W:
        w = int(rng.integers(34, 96))
        top = int(rng.integers(180, 410))
        d.rectangle([x, top, x + w, H], fill=int(rng.integers(40, 88)))
        x += w + int(rng.integers(0, 12))
    s = np.asarray(skyline.filter(ImageFilter.GaussianBlur(3)), np.float32) / 255
    city[..., 0] = s * 22
    city[..., 1] = s * 70
    city[..., 2] = s * 140
    f.poly([(cx - 72, 300), (cx - 210, 690), (cx + 190, 690), (cx + 80, 300)])
    f.limb([(cx - 34, 470), (cx - 62, 690)], 62, 54)
    f.limb([(cx + 34, 470), (cx + 64, 690)], 62, 54)
    f.poly([(cx - 90, 490), (cx - 112, 280), (cx - 74, 226), (cx + 74, 226), (cx + 112, 280), (cx + 90, 490)])
    f.disc(cx - 108, 268, 40, 32)
    f.disc(cx + 108, 268, 40, 32)
    f.limb([(cx, 230), (cx, 198)], 44)
    f.disc(cx, 150, 50, 58)
    f.limb([(cx - 112, 280), (cx - 164, 360), (cx - 204, 300)], 44, 32)
    f.limb([(cx + 110, 284), (cx + 146, 400), (cx + 136, 470)], 44, 32)
    f.lit_line([(cx - 208, 92), (cx - 208, 690)], (120, 200, 255), 5)
    f.lit_ring(cx - 208, 92, 22, (150, 220, 255), 4)
    f.lit_poly([(cx - 34, 138), (cx + 34, 138), (cx + 26, 152), (cx - 26, 152)], (140, 225, 255))
    f.lit_disc(cx, 280, 12, (130, 210, 255))
    return compose(f, (4, 8, 18), (20, 110, 230), (60, 30, 140), 33, behind=city)


def cricketer():
    """JioHotstar: a batter mid-swing under floodlights."""
    f = Figure()
    cx = 880
    behind = beams([(560, -30, 1.2), (1240, -30, 1.95), (900, -60, 1.57)], 0.34, (230, 80, 220))
    lights = Figure()
    f.limb([(cx - 18, 420), (cx - 112, 540), (cx - 158, 690)], 68, 46)
    f.limb([(cx + 22, 420), (cx + 112, 520), (cx + 96, 690)], 68, 46)
    f.disc(cx - 164, 672, 44, 20)
    f.disc(cx + 112, 676, 44, 20)
    f.poly([(cx - 66, 440), (cx - 84, 290), (cx - 46, 244), (cx + 64, 250), (cx + 88, 300), (cx + 66, 444)])
    f.limb([(cx + 10, 250), (cx + 2, 214)], 40)
    f.disc(cx - 2, 170, 50, 50)
    f.poly([(cx - 58, 168), (cx - 94, 168), (cx - 94, 182), (cx - 50, 186)])
    f.limb([(cx - 72, 290), (cx - 150, 280), (cx - 230, 232)], 40, 30)
    f.limb([(cx + 76, 298), (cx - 40, 306), (cx - 226, 240)], 40, 30)
    f.limb([(cx - 230, 232), (cx - 276, 190)], 15)
    f.poly([(cx - 268, 204), (cx - 292, 182), (cx - 392, 122), (cx - 376, 98), (cx - 272, 164)])
    for i in range(3):
        f.limb([(cx + 202 + i * 30, 690), (cx + 202 + i * 30, 492)], 9)
    f.lit_poly([(cx - 62, 164), (cx - 90, 164), (cx - 90, 170), (cx - 58, 172)], (255, 180, 255))
    f.lit_line([(cx - 284, 170), (cx - 380, 112)], (255, 140, 240), 3)
    f.lit_disc(cx - 452, 170, 9, (255, 255, 255))
    del lights
    return compose(f, (8, 4, 16), (180, 40, 210), (40, 60, 220), 44, behind=behind, cx=800, cy=240)


def champion():
    """Sony LIV: a champion raising a belt under a spotlight."""
    f = Figure()
    cx = 890
    behind = beams([(cx, -80, 1.57)], 0.42, (255, 150, 70), 0.44)
    ropes = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(ropes)
    for yy in (470, 530, 590):
        d.line([(400, yy), (W, yy - 8)], fill=120, width=4)
    r = np.asarray(ropes.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
    behind[..., 0] += r * 120
    behind[..., 1] += r * 50
    behind[..., 2] += r * 90
    f.limb([(cx - 40, 500), (cx - 84, 690)], 80, 64)
    f.limb([(cx + 40, 500), (cx + 84, 690)], 80, 64)
    f.poly([(cx - 74, 520), (cx - 134, 300), (cx - 110, 248), (cx + 110, 248), (cx + 134, 300), (cx + 74, 520)])
    f.disc(cx - 124, 278, 54, 44)
    f.disc(cx + 124, 278, 54, 44)
    f.limb([(cx, 250), (cx, 206)], 62, 54)
    f.disc(cx, 164, 52, 58)
    f.limb([(cx - 140, 278), (cx - 196, 188), (cx - 150, 74)], 62, 44)
    f.limb([(cx + 140, 278), (cx + 196, 188), (cx + 150, 74)], 62, 44)
    f.lit_line([(cx - 150, 70), (cx - 60, 42), (cx + 60, 42), (cx + 150, 70)], (255, 190, 90), 13)
    f.lit_disc(cx, 44, 36, (255, 208, 110))
    f.lit_ring(cx, 44, 48, (255, 150, 60), 4)
    f.lit_line([(cx - 76, 518), (cx + 76, 518)], (255, 165, 70), 7)
    return compose(f, (12, 5, 16), (230, 100, 40), (110, 30, 170), 55, behind=behind, cx=890, cy=180)


def astronaut():
    """Apple TV: an astronaut on a grey moon with the Earth above."""
    f = Figure()
    cx = 880
    behind = stars(66)
    moon = Image.new("L", (W, H), 0)
    ImageDraw.Draw(moon).ellipse([1046, 132, 1214, 300], fill=255)
    p = np.asarray(moon.filter(ImageFilter.GaussianBlur(2)), np.float32) / 255
    sh = radial(1100, 186, 136, 136)
    behind[..., 0] += p * (24 + sh * 60)
    behind[..., 1] += p * (56 + sh * 120)
    behind[..., 2] += p * (110 + sh * 170)
    f.disc(cx - 60, 980, 980, 370)
    f.limb([(cx - 40, 480), (cx - 90, 660)], 88, 74)
    f.limb([(cx + 42, 480), (cx + 80, 660)], 88, 74)
    f.poly([(cx - 104, 500), (cx - 124, 288), (cx - 82, 244), (cx + 82, 244), (cx + 124, 288), (cx + 104, 500)])
    f.poly([(cx + 104, 270), (cx + 172, 270), (cx + 172, 452), (cx + 104, 452)])
    f.disc(cx, 174, 84, 88)
    f.limb([(cx - 118, 290), (cx - 186, 390), (cx - 170, 480)], 64, 48)
    f.limb([(cx + 118, 290), (cx + 152, 188), (cx + 134, 96)], 64, 48)
    f.lit_poly([(cx - 58, 148), (cx + 58, 148), (cx + 62, 204), (cx - 62, 204)], (150, 195, 240))
    f.lit_poly([(cx - 42, 158), (cx - 8, 158), (cx - 18, 186), (cx - 44, 186)], (235, 248, 255))
    f.lit_disc(cx - 40, 330, 6, (255, 90, 90))
    f.lit_disc(cx + 10, 330, 6, (120, 255, 170))
    f.lit_line([(cx - 60, 372), (cx + 60, 372)], (150, 190, 230), 4)
    return compose(f, (4, 5, 10), (120, 150, 190), (40, 50, 90), 66, behind=behind, cx=900, cy=240)


def messenger():
    """AirPlay: someone beaming a laptop's picture to a big screen."""
    f = Figure()
    cx = 950
    screen = np.zeros((H, W, 3), np.float32)
    big = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(big)
    d.rounded_rectangle([500, 124, 846, 318], 16, outline=255, width=6)
    d.polygon([(622, 278), (674, 222), (726, 278)], outline=255, width=6)
    d.arc([590, 166, 758, 334], 215, 325, fill=255, width=6)
    a = np.asarray(big, np.float32) / 255
    wide = np.asarray(big.filter(ImageFilter.GaussianBlur(18)), np.float32) / 255
    screen[..., 0] = a * 150 + wide * 50
    screen[..., 1] = a * 215 + wide * 130
    screen[..., 2] = a * 255 + wide * 240
    f.limb([(cx - 34, 472), (cx - 56, 690)], 66, 56)
    f.limb([(cx + 34, 472), (cx + 56, 690)], 66, 56)
    f.poly([(cx - 92, 498), (cx - 104, 290), (cx - 68, 244), (cx + 68, 244), (cx + 104, 290), (cx + 92, 498)])
    f.limb([(cx, 246), (cx, 206)], 42)
    f.disc(cx, 162, 54, 60)
    f.limb([(cx - 94, 290), (cx - 140, 390), (cx - 184, 408)], 42, 30)
    f.limb([(cx + 94, 290), (cx + 84, 404), (cx - 80, 416)], 42, 30)
    f.poly([(cx - 268, 422), (cx - 46, 422), (cx - 46, 434), (cx - 268, 434)])
    f.poly([(cx - 268, 422), (cx - 300, 306), (cx - 94, 306), (cx - 46, 422)])
    f.lit_poly([(cx - 258, 414), (cx - 288, 316), (cx - 104, 316), (cx - 64, 414)], (110, 190, 255))
    for i, (xx, yy) in enumerate([(cx - 310, 300), (cx - 372, 274), (cx - 432, 258)]):
        f.lit_disc(xx, yy, 7 - i, (160, 225, 255))
    return compose(f, (4, 8, 16), (40, 130, 235), (30, 60, 150), 77, behind=screen, cx=760, cy=240)


def collector():
    """Play Store: a backpacker opening a glowing chest of new apps."""
    f = Figure()
    cx = 930
    f.limb([(cx - 24, 450), (cx - 96, 560), (cx - 92, 690)], 66, 50)
    f.limb([(cx + 32, 450), (cx + 130, 560), (cx + 142, 690)], 66, 50)
    f.poly([(cx - 74, 470), (cx - 92, 286), (cx - 62, 238), (cx + 66, 238), (cx + 96, 286), (cx + 78, 470)])
    f.poly([(cx + 80, 244), (cx + 176, 262), (cx + 186, 450), (cx + 84, 460)])
    f.limb([(cx, 240), (cx - 6, 206)], 42)
    f.disc(cx - 8, 160, 52, 58)
    f.poly([(cx - 86, 138), (cx + 70, 138), (cx + 54, 92), (cx - 8, 72), (cx - 72, 92)])
    f.poly([(cx - 118, 142), (cx + 92, 142), (cx + 92, 154), (cx - 118, 154)])
    f.limb([(cx - 80, 292), (cx - 174, 372), (cx - 268, 448)], 40, 30)
    f.limb([(cx + 74, 300), (cx - 40, 420), (cx - 220, 482)], 40, 30)
    f.poly([(cx - 410, 520), (cx - 180, 520), (cx - 180, 672), (cx - 410, 672)])
    f.poly([(cx - 420, 500), (cx - 170, 500), (cx - 200, 430), (cx - 390, 430)])
    f.lit_poly([(cx - 404, 514), (cx - 186, 514), (cx - 186, 524), (cx - 404, 524)], (160, 255, 190))
    f.lit_disc(cx - 356, 386, 7, (140, 255, 170))
    f.lit_disc(cx - 306, 348, 10, (255, 220, 110))
    f.lit_disc(cx - 248, 372, 8, (120, 200, 255))
    f.lit_disc(cx - 288, 286, 6, (255, 120, 120))
    behind = beams([(cx - 295, 520, -1.57)], 0.6, (60, 240, 130), 0.5)
    return compose(f, (4, 10, 8), (24, 170, 96), (20, 80, 120), 88, behind=behind, cx=760, cy=340)


def mechanic():
    """Settings: a small robot holding a wrench, surrounded by gears."""
    f = Figure()
    cx = 900
    behind = np.zeros((H, W, 3), np.float32)
    gears = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(gears)
    for gx, gy, gr, teeth in [(650, 244, 92, 10), (1136, 276, 112, 12), (1160, 500, 62, 8)]:
        d.ellipse([gx - gr, gy - gr, gx + gr, gy + gr], outline=255, width=12)
        d.ellipse([gx - gr // 3, gy - gr // 3, gx + gr // 3, gy + gr // 3], outline=255, width=8)
        for k in range(teeth):
            ang = 2 * np.pi * k / teeth
            d.line([(gx + np.cos(ang) * gr, gy + np.sin(ang) * gr),
                    (gx + np.cos(ang) * (gr + 22), gy + np.sin(ang) * (gr + 22))], fill=255, width=20)
    g = np.asarray(gears.filter(ImageFilter.GaussianBlur(1.6)), np.float32) / 255
    behind[..., 0] = g * 80
    behind[..., 1] = g * 52
    behind[..., 2] = g * 18
    f.limb([(cx - 54, 520), (cx - 64, 690)], 58)
    f.limb([(cx + 54, 520), (cx + 64, 690)], 58)
    f.d.rounded_rectangle([(cx - 128) * SS, 278 * SS, (cx + 128) * SS, 548 * SS], 34 * SS, fill=255)
    f.limb([(cx, 278), (cx, 244)], 30)
    f.d.rounded_rectangle([(cx - 102) * SS, 110 * SS, (cx + 102) * SS, 252 * SS], 30 * SS, fill=255)
    f.limb([(cx, 110), (cx, 62)], 7)
    f.limb([(cx - 132, 306), (cx - 212, 396), (cx - 268, 322)], 42, 34)
    f.limb([(cx + 132, 306), (cx + 202, 420), (cx + 180, 500)], 42, 34)
    f.limb([(cx - 268, 322), (cx - 338, 192)], 20)
    f.disc(cx - 346, 176, 32)
    f.lit_disc(cx, 58, 9, (255, 200, 90))
    f.lit_disc(cx - 46, 176, 22, (255, 200, 90))
    f.lit_disc(cx + 46, 176, 22, (255, 200, 90))
    f.lit_ring(cx, 406, 54, (255, 170, 60), 5)
    f.lit_disc(cx, 406, 18, (255, 200, 110))
    return compose(f, (12, 8, 4), (205, 130, 40), (120, 60, 30), 99, behind=behind, cx=900, cy=300)


# Package name, drawing, and the line shown above the row while that tile has focus.
AVATARS = [
    ("com.netflix.ninja", hooded_knight, "One more episode."),
    ("com.google.android.youtube.tv", creator, "Just one more video."),
    ("com.amazon.amazonvideo.livingroom", voyager, "Adventure, on demand."),
    ("in.startv.hotstar", cricketer, "Six to win. Last ball."),
    ("com.sonyliv", champion, "And still champion."),
    ("com.apple.atve.androidtv.appletv", astronaut, "Worlds away, tonight."),
    ("io.github.jqssun.airplay", messenger, "From your Mac to the wall."),
    ("com.android.vending", collector, "Find something new."),
    ("com.android.tv.settings", mechanic, "Tune things up."),
]


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    captions = []
    for package, draw, line in AVATARS:
        name = f"art_{package}.jpg"
        draw().save(out / name, quality=84, optimize=True, progressive=False, subsampling=1)
        captions.append(f"{name}\t{line}")
        print(name, (out / name).stat().st_size // 1024, "KB")
    (out / "captions.txt").write_text("\n".join(captions) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
