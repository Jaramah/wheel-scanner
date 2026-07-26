#!/usr/bin/env python3
"""Machine Money — faceless video build pipeline.

Renders 1920x1080 typographic slides (PIL), synthesizes voiceover
(espeak-ng) and a music bed (numpy), and assembles the final MP4 with
ffmpeg. Also emits captions.srt and chapters.txt for the upload.

Usage: python3 build_video.py <output_dir>
"""

import math
import os
import shutil
import struct
import subprocess
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
FPS = 30
CHUNK_PAUSE = 0.26      # silence after each caption chunk (s)
SEGMENT_PAUSE = 0.70    # extra silence between segments (s)

# MBROLA diphone voice — markedly smoother than espeak's default formant
# synth. Requires: apt install mbrola mbrola-us3 (falls back to en-us+m3).
VOICE = "mb-us3"
VOICE_FALLBACK = "en-us+m3"
SPEED = "143"

BG_TOP = (10, 14, 26)
BG_BOT = (19, 26, 46)
CYAN = (34, 211, 238)
VIOLET = (139, 92, 246)
YELLOW = (250, 204, 21)
WHITE = (245, 247, 250)
GREY = (148, 163, 184)

FONT_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"

# ---------------------------------------------------------------------------
# Script: segments -> (badge, title lines [(text, color)...], kicker, chunks)
# Caption chunks: words wrapped in * * render in yellow.
# ---------------------------------------------------------------------------

SEGMENTS = [
    dict(
        badge=None,
        title=[("7 AI SIDE HUSTLES", WHITE), ("THAT PAY", CYAN), ("IN 2026", WHITE)],
        kicker="NO HYPE. REAL NUMBERS.",
        chunks=[
            "Seven AI side hustles that are *actually paying* people in 2026.",
            "No fluff, and no ten thousand dollars overnight.",
            "Just *real models*, what they pay,",
            "and how to start *this week*. Let's go.",
        ],
    ),
    dict(
        badge="01",
        title=[("AI AUTOMATION", WHITE), ("FOR LOCAL BUSINESS", CYAN)],
        kicker="$200 – $1,000 / MONTH PER CLIENT",
        chunks=[
            "Number one. *AI automation* for local businesses.",
            "Dentists, gyms, roofers.",
            "They are drowning in *missed calls* and unanswered messages.",
            "You set up a simple *AI agent*",
            "that books appointments and answers common questions.",
            "Tools like Make and n8n do the heavy lifting.",
            "Businesses happily pay *two hundred to a thousand dollars* a month for this.",
            "Land three clients, and that is *real money*.",
        ],
    ),
    dict(
        badge="02",
        title=[("FACELESS CONTENT", WHITE), ("SYSTEMS", CYAN)],
        kicker="ADS  →  SPONSORS  →  AFFILIATES",
        chunks=[
            "Number two. *Faceless content* systems.",
            "You are watching one *right now*.",
            "Script with AI. Generate the visuals. Edit once. *Repeat*.",
            "The channels winning in 2026 pick *one format*",
            "and post it *consistently*.",
            "Ad revenue is just the start.",
            "The real money is *sponsors and affiliate links*",
            "in high value niches like finance and software.",
        ],
    ),
    dict(
        badge="03",
        title=[("AI DIGITAL", WHITE), ("PRODUCTS", CYAN)],
        kicker="MAKE ONCE. SELL FOREVER.",
        chunks=[
            "Number three. AI assisted *digital products*.",
            "Notion templates. Planners. Mini courses. E-books.",
            "AI compresses creation time from *weeks to days*.",
            "You still need taste, and a *real audience problem* to solve.",
            "But once it is made,",
            "a digital product *sells while you sleep*.",
            "Marketplaces like Gumroad and Etsy handle the storefront.",
        ],
    ),
    dict(
        badge="04",
        title=[("AI PRINT", WHITE), ("ON DEMAND", CYAN)],
        kicker="NICHE DOWN. ZERO INVENTORY.",
        chunks=[
            "Number four. *Print on demand* with AI design.",
            "Generate designs. Put them on shirts, mugs and posters.",
            "Platforms like Printful print and ship.",
            "You *never touch inventory*.",
            "The winners in 2026 *niche down hard*.",
            "Designs for nurses. For gamers. For dog moms.",
            "Margins are thin, so *volume and niching* are everything.",
        ],
    ),
    dict(
        badge="05",
        title=[("AI VOICE +", WHITE), ("DUBBING SERVICES", CYAN)],
        kicker="SELL THE QUALITY CONTROL.",
        chunks=[
            "Number five. AI *voiceover and translation* services.",
            "Creators want their content in *five languages*.",
            "Businesses want training videos narrated.",
            "AI tools do *ninety percent* of the work.",
            "You are selling the *quality control* on top of it.",
            "Package it as a service on Fiverr or Upwork,",
            "and charge *per finished minute*.",
        ],
    ),
    dict(
        badge="06",
        title=[("CUSTOM AI", WHITE), ("ASSISTANTS", CYAN)],
        kicker="BUILD FEE + MONTHLY RETAINER",
        chunks=[
            "Number six. Building *custom AI assistants* for niche industries.",
            "Real estate agents. Law firms. E-commerce stores.",
            "They don't want ChatGPT.",
            "They want *their* assistant, trained on *their* documents.",
            "If you can configure a chatbot, that is a skill *worth thousands*.",
            "Charge for the build.",
            "Then charge *monthly* to maintain it.",
        ],
    ),
    dict(
        badge="07",
        title=[("AI NICHE", WHITE), ("NEWSLETTER", CYAN)],
        kicker="OWN THE AUDIENCE.",
        chunks=[
            "Number seven. The AI powered *niche newsletter*.",
            "Pick a topic people have money in.",
            "AI tools. Real estate. Fitness.",
            "Use AI for research and drafts,",
            "add *your own take*, and publish weekly.",
            "Sponsors pay *per thousand readers*,",
            "and affiliate deals stack on top.",
            "It is slow to start, and completely worth it.",
            "You *own the audience*.",
        ],
    ),
    dict(
        badge=None,
        title=[("PICK ONE.", WHITE), ("90 DAYS.", YELLOW)],
        kicker="SUBSCRIBE — ONE DEEP DIVE EVERY WEEK",
        chunks=[
            "Here is the truth. *None of these are magic*.",
            "The people making money picked *one*,",
            "and gave it *ninety focused days*.",
            "So pick one. Start ugly. *Improve weekly*.",
            "Subscribe if you want the deep dive on each of these.",
            "We break down *one hustle per week*, with numbers.",
            "See you in the next one.",
        ],
    ),
]

# ---------------------------------------------------------------------------
# Slide rendering
# ---------------------------------------------------------------------------

def base_background(seed):
    img = Image.new("RGB", (W, H))
    top, bot = np.array(BG_TOP, float), np.array(BG_BOT, float)
    grad = np.linspace(0, 1, H)[:, None] * (bot - top)[None, :] + top[None, :]
    arr = np.repeat(grad[:, None, :], W, axis=1).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-350, -350, 550, 550], fill=(12, 60, 70))
    gd.ellipse([W - 550, H - 550, W + 350, H + 350], fill=(45, 28, 80))
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    img = Image.blend(img, Image.blend(img, glow, 0.9), 0.55)

    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 14, (H, W, 1), dtype=np.uint8).repeat(3, axis=2)
    img = Image.fromarray(np.clip(np.array(img).astype(int) + noise - 7, 0, 255).astype(np.uint8))
    return img


def letterspaced(draw, xy, text, font, fill, tracking=8, anchor_center=None):
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x, y = xy
    if anchor_center:
        x -= total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + tracking
    return total


def parse_marks(text):
    """Split '*hot* words' into [(word, highlighted)] keeping punctuation."""
    words, hot = [], False
    for tok in text.split():
        opens = tok.startswith("*")
        closes = "*" in (tok[1:] if opens else tok)
        clean = tok.replace("*", "")
        if opens and closes:
            words.append((clean, True))
        elif opens:
            hot = True
            words.append((clean, True))
        elif closes:
            words.append((clean, True))
            hot = False
        else:
            words.append((clean, hot))
    return words


def draw_caption(img, text):
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_BOLD, 56)
    words = parse_marks(text)
    space = d.textlength(" ", font=font)

    lines, cur, cur_w = [], [], 0
    for wtext, hot in words:
        wl = d.textlength(wtext, font=font)
        if cur and cur_w + space + wl > W - 380:
            lines.append(cur)
            cur, cur_w = [], 0
        cur.append((wtext, hot, wl))
        cur_w += (space if len(cur) > 1 else 0) + wl
    if cur:
        lines.append(cur)

    line_h = 74
    y0 = H - 150 - line_h * (len(lines) - 1)
    box_top = y0 - 30
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([120, box_top, W - 120, H - 78], radius=26, fill=(5, 8, 16, 165))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)

    for i, line in enumerate(lines):
        total = sum(wl for _, _, wl in line) + space * (len(line) - 1)
        x = (W - total) / 2
        y = y0 + i * line_h
        for wtext, hot, wl in line:
            color = YELLOW if hot else WHITE
            d.text((x + 2, y + 3), wtext, font=font, fill=(0, 0, 0))
            d.text((x, y), wtext, font=font, fill=color)
            x += wl + space


def render_slide(seg, seg_index, chunk_text, progress, path):
    img = base_background(seed=seg_index * 7 + 1)
    d = ImageDraw.Draw(img)

    tag_font = ImageFont.truetype(FONT_BOLD, 30)
    letterspaced(d, (96, 64), "MACHINE MONEY", tag_font, CYAN, tracking=10)
    d.line([96, 112, 405, 112], fill=(34, 211, 238, 120), width=3)

    if seg["badge"]:
        ghost_font = ImageFont.truetype(FONT_BOLD, 640)
        gw = d.textlength(seg["badge"], font=ghost_font)
        ghost = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(ghost)
        gd.text((W - gw - 60, 60), seg["badge"], font=ghost_font,
                fill=(90, 110, 160, 34))
        img = Image.alpha_composite(img.convert("RGBA"), ghost).convert("RGB")
        d = ImageDraw.Draw(img)

        badge_font = ImageFont.truetype(FONT_BOLD, 64)
        d.rounded_rectangle([96, 200, 268, 300], radius=20, outline=CYAN, width=4)
        bw = d.textlength(seg["badge"], font=badge_font)
        d.text((96 + (172 - bw) / 2, 216), seg["badge"], font=badge_font, fill=CYAN)
        title_y = 350
    else:
        title_y = 260

    title_font = ImageFont.truetype(FONT_BOLD, 108)
    for line, color in seg["title"]:
        d.text((100, title_y + 4), line, font=title_font, fill=(0, 0, 0))
        d.text((96, title_y), line, font=title_font, fill=color)
        title_y += 128

    kicker_font = ImageFont.truetype(FONT_BOLD, 40)
    kw = (sum(d.textlength(c, font=kicker_font) for c in seg["kicker"])
          + 3 * (len(seg["kicker"]) - 1))
    d.rounded_rectangle([96, title_y + 36, 96 + kw + 60, title_y + 116],
                        radius=14, outline=VIOLET, width=3)
    letterspaced(d, (96 + 30, title_y + 54), seg["kicker"], kicker_font, GREY, tracking=3)

    draw_caption(img, chunk_text)

    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 10, int(W * progress), H], fill=CYAN)
    img.save(path, "PNG")


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

def tts_chunk(text, path):
    clean = text.replace("*", "")
    voice = VOICE
    if subprocess.run(["espeak-ng", "-v", voice, "-q", "x"],
                      capture_output=True).returncode != 0:
        voice = VOICE_FALLBACK
    subprocess.run(
        ["espeak-ng", "-v", voice, "-s", SPEED, "-a", "180", "-w", path, clean],
        check=True, capture_output=True)
    with wave.open(path, "rb") as wf:
        sr = wf.getframerate()
        data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return sr, data


def music_bed(duration, sr):
    """Soft ambient pad, Am–F–C–G loop with a gentle pluck."""
    chords = [
        [220.0, 261.63, 329.63],        # A minor
        [174.61, 220.0, 261.63],        # F major
        [130.81, 196.0, 261.63, 329.63],  # C major
        [196.0, 246.94, 293.66],        # G major
    ]
    bar = 4.0
    total = int(duration * sr)
    out = np.zeros(total, dtype=np.float64)
    t_bar = np.arange(int(bar * sr)) / sr
    env = np.minimum(1, t_bar / 1.2) * np.minimum(1, (bar - t_bar) / 1.2)
    rng = np.random.default_rng(11)
    pos = 0
    i = 0
    while pos < total:
        chord = chords[i % 4]
        seg = np.zeros_like(t_bar)
        for f in chord:
            seg += 0.28 * np.sin(2 * np.pi * f * t_bar)
            seg += 0.10 * np.sin(2 * np.pi * f * 2 * t_bar + 0.5)
        seg *= env
        # sparse pluck an octave up
        if i % 2 == 1:
            f = chord[rng.integers(len(chord))] * 2
            pt = t_bar - 2.0
            pluck = np.where(pt > 0, np.exp(-pt * 3.5), 0) * np.sin(2 * np.pi * f * t_bar)
            seg += 0.12 * pluck
        n = min(len(seg), total - pos)
        out[pos:pos + n] += seg[:n]
        pos += n
        i += 1
    out /= max(1e-9, np.max(np.abs(out)))
    return (out * 32767 * 0.85).astype(np.int16)


def write_wav(path, sr, data):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(data.tobytes())


def fmt_srt(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

COLOR_NAMES = {"white": WHITE, "cyan": CYAN, "yellow": YELLOW,
               "violet": VIOLET, "grey": GREY}


def load_segments(outdir):
    """Per-video script from <outdir>/script.json, else built-in SEGMENTS."""
    path = os.path.join(outdir, "script.json")
    if not os.path.exists(path):
        return SEGMENTS
    import json
    with open(path) as f:
        raw = json.load(f)
    return [dict(badge=s.get("badge"), kicker=s["kicker"],
                 title=[(t, COLOR_NAMES[c]) for t, c in s["title"]],
                 chunks=s["chunks"]) for s in raw]


def main(outdir):
    segments = load_segments(outdir)
    work = os.path.join(outdir, "work")
    slides = os.path.join(work, "slides")
    os.makedirs(slides, exist_ok=True)

    total_chunks = sum(len(s["chunks"]) for s in segments)
    chunk_meta = []   # (png, duration, text, start)
    voice_parts = []
    sr = None
    t = 0.0
    chapters = []
    ci = 0

    for si, seg in enumerate(segments):
        chapters.append((t, seg))
        for li, text in enumerate(seg["chunks"]):
            wav_path = os.path.join(work, f"tts_{ci:03d}.wav")
            csr, data = tts_chunk(text, wav_path)
            sr = sr or csr
            assert csr == sr
            pause = CHUNK_PAUSE + (SEGMENT_PAUSE if li == len(seg["chunks"]) - 1 else 0)
            raw_dur = len(data) / sr + pause
            dur = math.ceil(raw_dur * FPS) / FPS
            pad = int(dur * sr) - len(data)
            voice_parts.append(np.concatenate([data, np.zeros(pad, dtype=np.int16)]))

            png = os.path.join(slides, f"chunk_{ci:03d}.png")
            render_slide(seg, si, text, progress=(ci + 1) / total_chunks, path=png)
            chunk_meta.append((png, dur, text, t))
            t += dur
            ci += 1
            print(f"  chunk {ci}/{total_chunks}  {dur:5.2f}s  {text[:50]}")

    total_dur = t
    print(f"Total duration: {total_dur:.1f}s")

    voice = np.concatenate(voice_parts)
    write_wav(os.path.join(work, "voice.wav"), sr, voice)
    write_wav(os.path.join(work, "music.wav"), sr, music_bed(total_dur, sr))

    concat = os.path.join(work, "list.txt")
    with open(concat, "w") as f:
        for png, dur, _, _ in chunk_meta:
            f.write(f"file '{os.path.abspath(png)}'\nduration {dur:.6f}\n")
        f.write(f"file '{os.path.abspath(chunk_meta[-1][0])}'\n")

    srt_path = os.path.join(outdir, "captions.srt")
    with open(srt_path, "w") as f:
        for i, (_, dur, text, start) in enumerate(chunk_meta, 1):
            f.write(f"{i}\n{fmt_srt(start)} --> {fmt_srt(start + dur - 0.05)}\n"
                    f"{text.replace('*', '')}\n\n")

    with open(os.path.join(outdir, "chapters.txt"), "w") as f:
        for start, seg in chapters:
            m, s = int(start) // 60, int(start) % 60
            label = " ".join(l for l, _ in seg["title"])
            f.write(f"{m:d}:{s:02d} {label.title()}\n")

    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    out_mp4 = os.path.join(outdir, "video.mp4")
    cmd = [
        ffmpeg, "-y",
        "-f", "concat", "-safe", "0", "-i", concat,
        "-i", os.path.join(work, "voice.wav"),
        "-i", os.path.join(work, "music.wav"),
        "-filter_complex",
        "[0:v]fps=30,scale=1920:1080,setsar=1[v];"
        "[1:a]highpass=f=90,lowpass=f=9500,"
        "acompressor=threshold=-18dB:ratio=3:attack=10:release=120,"
        "volume=1.8[vo];"
        "[2:a]volume=0.10[mu];"
        "[vo][mu]amix=inputs=2:duration=first:normalize=0,"
        "alimiter=limit=0.89:level=false[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
        "-shortest", out_mp4,
    ]
    subprocess.run(cmd, check=True)
    print("Wrote", out_mp4)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
