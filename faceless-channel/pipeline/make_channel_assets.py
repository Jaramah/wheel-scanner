#!/usr/bin/env python3
"""Machine Money — channel branding assets: logo, banner, video thumbnail.

Usage: python3 make_channel_assets.py <channel_kit_dir> <video_dir>
"""

import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

CYAN = (34, 211, 238)
VIOLET = (139, 92, 246)
YELLOW = (250, 204, 21)
WHITE = (245, 247, 250)
GREY = (148, 163, 184)
BG_TOP = (10, 14, 26)
BG_BOT = (19, 26, 46)

FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"


def gradient_bg(w, h, glow_seed=3):
    top, bot = np.array(BG_TOP, float), np.array(BG_BOT, float)
    grad = np.linspace(0, 1, h)[:, None] * (bot - top)[None, :] + top[None, :]
    img = Image.fromarray(np.repeat(grad[:, None, :], w, axis=1).astype(np.uint8))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-w // 4, -h // 4, w // 3, h // 3], fill=(12, 60, 70))
    gd.ellipse([w - w // 3, h - h // 3, w + w // 4, h + h // 4], fill=(45, 28, 80))
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    return Image.blend(img, Image.blend(img, glow, 0.9), 0.55)


def letterspaced(draw, xy, text, font, fill, tracking=8, center_x=None):
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x, y = xy
    if center_x is not None:
        x = center_x - total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + tracking


def make_logo(path):
    s = 800
    img = gradient_bg(s, s)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([40, 40, s - 40, s - 40], radius=120, outline=CYAN, width=10)
    f = ImageFont.truetype(FONT_BOLD, 340)
    mw = d.textlength("M", font=f)
    d.text((s / 2 - mw - 8, 160), "M", font=f, fill=WHITE)
    d.text((s / 2 + 8, 160), "M", font=f, fill=CYAN)
    fd = ImageFont.truetype(FONT_BOLD, 90)
    letterspaced(d, (0, 570), "MACHINE", fd, WHITE, tracking=14, center_x=s / 2)
    letterspaced(d, (0, 665), "MONEY", fd, CYAN, tracking=30, center_x=s / 2)
    img.save(path)


def make_banner(path):
    w, h = 2560, 1440
    img = gradient_bg(w, h)
    d = ImageDraw.Draw(img)
    # safe area 1546x423 centered
    cx, cy = w / 2, h / 2
    f1 = ImageFont.truetype(FONT_BOLD, 130)
    t1w = d.textlength("MACHINE ", font=f1) + d.textlength("MONEY", font=f1)
    d.text((cx - t1w / 2, cy - 150), "MACHINE ", font=f1, fill=WHITE)
    d.text((cx - t1w / 2 + d.textlength("MACHINE ", font=f1), cy - 150),
           "MONEY", font=f1, fill=CYAN)
    f2 = ImageFont.truetype(FONT_BOLD, 46)
    letterspaced(d, (0, cy + 30), "AI. MONEY. NO FLUFF.", f2, GREY,
                 tracking=6, center_x=cx)
    f3 = ImageFont.truetype(FONT_BOLD, 34)
    letterspaced(d, (0, cy + 110), "NEW DEEP DIVE EVERY WEEK", f3, VIOLET,
                 tracking=4, center_x=cx)
    d.line([cx - 380, cy - 175, cx + 380, cy - 175], fill=CYAN, width=4)
    img.save(path)


def make_thumbnail(path):
    w, h = 1280, 720
    img = gradient_bg(w, h)
    d = ImageDraw.Draw(img)

    ghost = ImageFont.truetype(FONT_BOLD, 560)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((w - 400, 40), "$", font=ghost, fill=(34, 211, 238, 46))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    d = ImageDraw.Draw(img)

    f_big = ImageFont.truetype(FONT_BOLD, 165)
    d.text((66, 66), "7", font=f_big, fill=(0, 0, 0))
    d.text((60, 60), "7", font=f_big, fill=YELLOW)
    f1 = ImageFont.truetype(FONT_BOLD, 110)
    d.text((216, 76), "AI SIDE", font=f1, fill=(0, 0, 0))
    d.text((210, 70), "AI SIDE", font=f1, fill=WHITE)
    d.text((216, 206), "HUSTLES", font=f1, fill=(0, 0, 0))
    d.text((210, 200), "HUSTLES", font=f1, fill=WHITE)

    f2 = ImageFont.truetype(FONT_BOLD, 92)
    d.text((66, 366), "THAT PAY", font=f2, fill=(0, 0, 0))
    d.text((60, 360), "THAT PAY", font=f2, fill=CYAN)
    d.text((66, 476), "IN 2026", font=f2, fill=(0, 0, 0))
    d.text((60, 470), "IN 2026", font=f2, fill=CYAN)

    badge_f = ImageFont.truetype(FONT_BOLD, 44)
    badge_text = "REAL NUMBERS INSIDE"
    bw = d.textlength(badge_text, font=badge_f)
    d.rounded_rectangle([60, 610, 60 + bw + 48, 686], radius=16, fill=(250, 204, 21))
    d.text((84, 624), badge_text, font=badge_f, fill=(10, 14, 26))
    img.save(path)


if __name__ == "__main__":
    kit, vid = sys.argv[1], sys.argv[2]
    make_logo(f"{kit}/logo.png")
    make_banner(f"{kit}/banner.png")
    make_thumbnail(f"{vid}/thumbnail.png")
    print("assets done")
