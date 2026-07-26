#!/usr/bin/env python3
"""Generic Machine Money thumbnail generator.

Usage: python3 make_thumbnail.py <out.png> <spec.json>

spec.json:
{
  "corner":  "7",                       # big yellow corner mark (optional)
  "lines":   [["AI SIDE", "white"], ["HUSTLES", "white"],
              ["THAT PAY", "cyan"]],    # up to 4 lines, top to bottom
  "badge":   "REAL NUMBERS INSIDE",     # yellow pill (optional)
  "ghost":   "$"                        # huge translucent glyph, right side
}
"""

import json
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from make_channel_assets import gradient_bg, CYAN, YELLOW, WHITE, VIOLET

FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
COLORS = {"white": WHITE, "cyan": CYAN, "yellow": YELLOW, "violet": VIOLET}


def make(out_path, spec):
    w, h = 1280, 720
    img = gradient_bg(w, h)

    if spec.get("ghost"):
        ghost = ImageFont.truetype(FONT_BOLD, 560)
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((w - 420, 40), spec["ghost"], font=ghost, fill=(34, 211, 238, 46))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    d = ImageDraw.Draw(img)
    x0, y = 60, 60

    if spec.get("corner"):
        f_big = ImageFont.truetype(FONT_BOLD, 165)
        d.text((x0 + 6, y + 6), spec["corner"], font=f_big, fill=(0, 0, 0))
        d.text((x0, y), spec["corner"], font=f_big, fill=YELLOW)
        text_x = x0 + int(d.textlength(spec["corner"], font=f_big)) + 40
    else:
        text_x = x0

    sizes = {1: 150, 2: 120, 3: 105, 4: 92}
    size = sizes.get(len(spec["lines"]), 92)
    f = ImageFont.truetype(FONT_BOLD, size)
    for i, (text, color) in enumerate(spec["lines"]):
        lx = text_x if (spec.get("corner") and i < 2) else x0
        d.text((lx + 6, y + 6), text, font=f, fill=(0, 0, 0))
        d.text((lx, y), text, font=f, fill=COLORS[color])
        y += size + 22

    if spec.get("badge"):
        badge_f = ImageFont.truetype(FONT_BOLD, 44)
        bw = d.textlength(spec["badge"], font=badge_f)
        d.rounded_rectangle([60, 610, 60 + bw + 48, 686], radius=16, fill=YELLOW)
        d.text((84, 624), spec["badge"], font=badge_f, fill=(10, 14, 26))

    img.save(out_path)
    print("wrote", out_path)


if __name__ == "__main__":
    with open(sys.argv[2]) as f:
        make(sys.argv[1], json.load(f))
