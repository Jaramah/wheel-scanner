# Machine Money — Faceless YouTube Channel

A complete faceless-channel kit: branding, strategy, an automated video
production pipeline, and a finished, upload-ready first video.

## Why this niche (research-backed, July 2026)

- **AI tools** and **personal finance** are the two highest-RPM faceless
  niches right now ($15–$30+ RPM in finance; heavy SaaS/tech ad spend on AI
  content). Machine Money sits at their intersection: *making money with AI*.
- The July 2026 meta-trend: audiences reward **repeatable formats tied to
  timely moments** and **authenticity over polish**. This channel's angle is
  deliberately no-hype — "real models, real numbers" — which differentiates
  it from the saturated get-rich-quick corner of the niche.
- Faceless typographic/caption-driven videos (bold text slides, keyword
  highlights, progress bar) are the current winning visual format and are
  fully automatable — no stock footage licensing needed.

Sources: NexLev, Fliki, GoFaceless and OutlierKit niche reports (2026);
mean.ceo July 2026 viral-trends report.

## Channel identity

| | |
|---|---|
| Name | **Machine Money** |
| Handle | `@MachineMoneyHQ` |
| Tagline | AI. Money. No fluff. |
| Format | Weekly listicle deep dive, 4–6 min, faceless typographic style |
| Palette | Dark navy `#0a0e1a` / cyan `#22d3ee` / violet `#8b5cf6` / yellow `#facc15` |

See `channel-kit/` for logo, banner, and the About-page copy.

## Repo layout

```
faceless-channel/
├── channel-kit/            # logo.png, banner.png, about.md
├── pipeline/               # automated production pipeline
│   ├── build_video.py      # script → slides + TTS + music → final MP4 + SRT
│   └── make_channel_assets.py
└── videos/
    └── 001-ai-side-hustles/
        ├── video.mp4       # upload-ready 1080p video
        ├── thumbnail.png   # 1280x720 thumbnail
        ├── captions.srt    # upload alongside the video
        ├── chapters.txt    # paste into the description
        ├── script.md       # full narration script
        └── metadata.md     # title, description, tags — copy/paste at upload
```

## Producing the next video

1. Edit the `SEGMENTS` list at the top of `pipeline/build_video.py`
   (new title cards + caption chunks; `*word*` = yellow highlight).
2. Run `python3 pipeline/build_video.py videos/00X-topic/`.
3. Regenerate a thumbnail variant in `make_channel_assets.py`.

Requires: `pip install pillow numpy imageio-ffmpeg` and `espeak-ng`.
Tip: for a more natural voice, swap the `tts_chunk` function for any
neural TTS (ElevenLabs, OpenAI TTS, Piper) — the rest of the pipeline is
unchanged.

## Content calendar (first 8 weeks)

Weekly uploads, same format, each a deep dive on one hustle from video 001:

1. 7 AI Side Hustles That Actually Pay in 2026 *(this video — the pillar)*
2. AI Automation for Local Businesses — full walkthrough with pricing
3. Faceless Content Systems — the exact pipeline (meta episode)
4. AI Digital Products — 0 to first sale
5. AI Print-on-Demand — niching case studies
6. AI Voiceover Services — packaging and pricing
7. Custom AI Assistants — landing the first client
8. AI Niche Newsletters — sponsor math explained

The pillar video links out to each deep dive as it publishes (end screens +
pinned comment), building a self-reinforcing watch loop.
