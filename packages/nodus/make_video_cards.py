#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate the static video cards for the 3-min Nodus video
(companion to `video_shooting_checklist.md`).

Produces PNG cards ready to drop into the editor:
  video_cards/titre_card.png       (1920x1080)  segment 1 — title
  video_cards/task_card.png        (1600x900)   segment 2 — the task
  video_cards/modele_card.png      (1600x900)   segment 2 — the model
  video_cards/plan_card.png        (1600x900)   segment 2 — the plan
  video_cards/metrics_card.png     (1600x900)   segment 4 — 99%
  video_cards/signtest_card.png    (1600x900)   segment 4 — p = 0.0139
  video_cards/wiring_gcs_card.png  (1600x900)   segment 5 — GCS delivery wiring
  video_cards/grafana_map_card.png (1600x900)   segment 5 — event stream → Grafana
  video_cards/repo_card.png        (1600x900)   segment 6 — open source close

Palette + fonts + measured-layout guard reused from make_gallery_image.py
(no drawn box may overlap; exit 1 on violation with --strict).

Usage:
    python make_video_cards.py [--out video_cards] [--strict]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Palette (same as make_gallery_image.py) ──────────────────────────────
PAGE      = (10, 15, 22)      # #0a0f16
SURFACE   = (18, 27, 38)      # #121b26
RAISED    = (23, 34, 49)      # #172231
BORDER    = (42, 60, 82)      # #2a3c52
INK       = (234, 242, 251)   # #eaf2fb
INK_SOFT  = (172, 193, 214)   # #acc1d6
INK_MUTED = (126, 145, 168)   # #7e91a8
GREEN     = (12, 163, 12)     # #0ca30c
GRAFANA   = (244, 104, 0)     # #f46800
C_TASK    = (57, 135, 229)    # #3987e5
C_PLAN    = (217, 89, 38)     # #d95926
C_CALL    = (25, 158, 112)    # #199e70
C_RES     = (201, 133, 0)     # #c98500
GOOGLE_BLUE = (66, 133, 244)  # #4285f4
ON_HUE    = (8, 16, 24)

FW = r"C:\Windows\Fonts"
def _f(name, size):
    return ImageFont.truetype(f"{FW}\\{name}", size)

F_TITLE   = _f("segoeuib.ttf", 33)
F_XL      = _f("segoeuib.ttf", 64)
F_BIG     = _f("segoeuib.ttf", 44)
F_SUB     = _f("segoeui.ttf", 16)
F_SUB_B   = _f("seguisb.ttf", 16)
F_PANEL   = _f("seguisb.ttf", 15)
F_TASK    = _f("segoeui.ttf", 20)
F_CHIP    = _f("seguisb.ttf", 14)
F_MONO    = _f("consola.ttf", 17)
F_MONO_B  = _f("consolab.ttf", 17)
F_TINY    = _f("segoeui.ttf", 13)
F_TINY_B  = _f("seguisb.ttf", 13)

DRAWN = []  # (label, x0, y0, x1, y1)


def txt(d, x, y, s, font, fill, label="", anchor="lm"):
    ink = d.textbbox((x, y), s, font=font, anchor=anchor)
    DRAWN.append((label, ink[0], ink[1], ink[2], ink[3]))
    d.text((x, y), s, font=font, fill=fill, anchor=anchor)


def center(d, cx, cy, s, font, fill, label=""):
    """Center a string on (cx, cy)."""
    w = d.textlength(s, font=font)
    ink = d.textbbox((0, 0), s, font=font)
    h = ink[3] - ink[1]
    txt(d, cx - w / 2, cy - h / 2, s, font, fill, label=label)


def rr(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def chip(d, x, cy, text, font, fg, bg, pad=(10, 5), r=6):
    w = d.textlength(text, font=font) + 2 * pad[0]
    h = font.size + 2 * pad[1]
    rr(d, [x, cy - h / 2, x + w, cy + h / 2], r, fill=bg)
    d.text((x + pad[0], cy), text, font=font, fill=fg, anchor="lm")
    DRAWN.append((f"chip:{text}", x, cy - h / 2, x + w, cy + h / 2))
    return x + w


def arrow(d, x0, x1, y):
    """Horizontal arrow between x0 and x1 at height y."""
    d.line([x0, y, x1 - 8, y], fill=INK_MUTED, width=2)
    d.polygon([(x1 - 10, y - 5), (x1 - 10, y + 5), (x1, y)], fill=INK_MUTED)
    DRAWN.append((f"arrow", x0, y - 6, x1, y + 6))


def header(d, title, subtitle, W):
    """Shared card header; returns the Y below the rule."""
    logo = 46
    rr(d, [40, 26, 40 + logo + 8, 26 + logo + 8], 10, fill=GRAFANA)
    txt(d, 40 + logo / 2 + 4, 26 + logo / 2 + 4, "N", F_TITLE, ON_HUE, label="logo", anchor="mm")
    txt(d, 40 + logo + 26, 34, "NODUS", F_BIG, INK, label="wordmark")
    txt(d, 40 + logo + 26, 66, title, F_SUB_B, INK_SOFT, label="card-title")
    txt(d, W - 40, 40, subtitle, F_TINY, INK_MUTED, label="card-sub", anchor="rm")
    d.line([40, 96, W - 40, 96], fill=BORDER, width=1)
    return 116


def check_overlaps():
    bad = []
    items = [e for e in DRAWN if not e[0].startswith("bg:")]
    for i in range(len(items)):
        a = items[i]
        for j in range(i + 1, len(items)):
            b = items[j]
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                bad.append((a[0], b[0]))
    return bad


def save_card(img, out, name, W, H):
    bad = check_overlaps()
    img.save(out)
    print(f"wrote {name} ({W}x{H}); {len(DRAWN)} boxes; "
          f"{'OK — no overlaps' if not bad else f'{len(bad)} OVERLAPS: {bad}'}")
    DRAWN.clear()
    return bad


# ── Card builders ─────────────────────────────────────────────────────────

def build_titre(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    # logo block centered
    bw, bh = 150, 150
    rr(d, [(W - bw) / 2, 260, (W + bw) / 2, 260 + bh], 28, fill=GRAFANA)
    txt(d, W / 2, 260 + bh / 2, "N", F_XL, ON_HUE, label="logo", anchor="mm")
    center(d, W / 2, 520, "NODUS", F_XL, INK, label="wordmark")
    center(d, W / 2, 600, "a tiny local planner", F_BIG, INK_SOFT, label="subtitle")
    center(d, W / 2, 652, "free agentic planning · observable · yours", F_SUB, INK_MUTED, label="tagline")
    d.line([W / 2 - 220, 706, W / 2 + 220, 706], fill=BORDER, width=1)
    # partner chips
    cx = W / 2
    w1 = d.textlength("Grafana Cloud · MCP", F_CHIP) + 20
    w2 = d.textlength("Google Cloud · Gemini + GCS", F_CHIP) + 20
    gap = 24
    x0 = cx - (w1 + gap + w2) / 2
    chip(d, x0, 760, "Grafana Cloud · MCP", F_CHIP, (255, 176, 102), (54, 30, 6))
    chip(d, x0 + w1 + gap, 760, "Google Cloud · Gemini + GCS", F_CHIP, ON_HUE, GOOGLE_BLUE)
    center(d, W / 2, 880, "github.com/Rua987/nodus", F_TINY, INK_MUTED, label="repo")
    return img


def build_task(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "THE TASK  ·  what the agent is asked to do", "segment 2", W)
    # task card
    rr(d, [100, y + 40, W - 100, y + 300], 14, fill=SURFACE, outline=BORDER)
    # drawn play glyph (U+25B6 not in the body fonts → tofu otherwise)
    ty = y + 76
    d.polygon([(122, ty - 7), (122, ty + 7), (135, ty)], fill=C_TASK)
    DRAWN.append(("task-glyph", 122, ty - 8, 135, ty + 8))
    txt(d, 160, y + 76, "TASK", F_PANEL, C_TASK, label="task-label")
    txt(d, 130, y + 190, 'Read src/utils.py, then save a config stub, then verify.',
        F_TASK, INK, label="task-text")
    txt(d, 130, y + 232, "a multi-step instruction — the shape a planner has to get right",
        F_TINY, INK_MUTED, label="task-note")
    return img


def build_modele(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "THE MODEL  ·  the tiny planner inside", "segment 2", W)
    txt(d, W / 2, y + 130, "324M", F_XL, C_TASK, label="params", anchor="mm")
    txt(d, W / 2, y + 210, "parameters", F_SUB, INK_MUTED, label="params-unit", anchor="mm")
    rr(d, [140, y + 300, W - 140, y + 480], 14, fill=SURFACE, outline=BORDER)
    specs = [
        "24 layers · 12 heads",
        "768 embedding dim",
        "vocab 100k · local transformer",
    ]
    sy = y + 360
    for i, s in enumerate(specs):
        txt(d, 200, sy + i * 44, s, F_SUB_B, INK_SOFT, label=f"spec:{i}")
    txt(d, 200, sy + 3 * 44 + 8,
        "trained on one job: turn a task into ordered tool names",
        F_TINY, INK_MUTED, label="spec-note")
    return img


def build_plan(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "THE PLAN  ·  what the 324M answers", "segment 2", W)
    rr(d, [100, y + 70, W - 100, y + 330], 14, fill=SURFACE, outline=BORDER)
    # mono array centered
    arr = '["read_file", "write_file", "bash"]'
    center(d, W / 2, y + 150, arr, F_MONO_B, INK, label="array")
    # chips with arrows
    tools = ["read_file", "write_file", "bash"]
    hues = [C_TASK, C_PLAN, C_CALL]
    total = sum(d.textlength(t, font=F_CHIP) + 20 for t in tools) + 40 * (len(tools) - 1)
    x = (W - total) / 2
    cy = y + 240
    for i, t in enumerate(tools):
        x = chip(d, x, cy, t, F_CHIP, ON_HUE, hues[i])
        if i < len(tools) - 1:
            arrow(d, x + 12, x + 44, cy)
            x += 56
    txt(d, W / 2, y + 300, "no arguments · no replanning — the harness fills the details",
        F_TINY, INK_MUTED, label="note", anchor="mm")
    return img


def build_metrics(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "THE EVIDENCE  ·  accuracy on a fresh holdout", "segment 4", W)
    txt(d, W / 2, y + 140, "119 / 120 = 99%", F_XL, GREEN, label="99pct", anchor="mm")
    # chips
    cy = y + 250
    x = W / 2 - 260
    x = chip(d, x, cy, "0 regressions", F_CHIP, ON_HUE, C_CALL)
    x = chip(d, x + 24, cy, "120 unseen tasks", F_CHIP, ON_HUE, C_PLAN)
    txt(d, W / 2, y + 340,
        "the model plans 119 of 120 tasks it has never seen — zero regressions",
        F_SUB_B, INK_SOFT, label="claim", anchor="mm")
    return img


def build_signtest(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "THE EVIDENCE  ·  does the plan help end to end?", "segment 4", W)
    rr(d, [140, y + 60, W - 140, y + 460], 14, fill=SURFACE, outline=BORDER)
    rows = [
        ("plan better", "27"),
        ("plan worse", "11"),
        ("tie / unchanged", "the rest"),
    ]
    ry = y + 120
    for i, (label, val) in enumerate(rows):
        txt(d, 200, ry + i * 56, label, F_SUB_B, INK_SOFT, label=f"row:{i}")
        txt(d, W - 200, ry + i * 56, val, F_MONO_B, INK, label=f"val:{i}", anchor="rm")
        if i < len(rows) - 1:
            d.line([200, ry + i * 56 + 26, W - 200, ry + i * 56 + 26], fill=BORDER, width=1)
    txt(d, W / 2, y + 320, "p = 0.0139", F_XL, GRAFANA, label="pval", anchor="mm")
    txt(d, W / 2, y + 390, "sign test · 2 seeds · 130/200 vs 113/200 · statistically significant",
        F_TINY, INK_MUTED, label="note", anchor="mm")
    return img


def build_wiring_gcs(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "GOOGLE CLOUD DELIVERY  ·  the gs:// upload", "segment 5", W)
    rr(d, [100, y + 50, W - 100, y + 360], 14, fill=SURFACE, outline=BORDER)
    steps = [
        "NODUS_GCLOUD=real",
        "google-cloud-storage  SDK",
        "GCLOUD_BUCKET + ADC",
    ]
    cy = y + 130
    x = 150
    for i, s in enumerate(steps):
        w = d.textlength(s, font=F_MONO_B)
        rr(d, [x, cy - 26, x + w + 30, cy + 26], 10, fill=RAISED, outline=BORDER)
        txt(d, x + 15, cy, s, F_MONO_B, C_TASK, label=f"wiring:{i}", anchor="lm")
        DRAWN.append((f"bg:wiringbox:{i}", x, cy - 26, x + w + 30, cy + 26))
        x += w + 30
        if i < len(steps) - 1:
            arrow(d, x + 4, x + 46, cy)
            x += 56
    rr(d, [100, y + 240, W - 100, y + 320], 10, fill=SURFACE, outline=(36, 74, 44))
    # drawn check (U+2713 not in the body fonts → tofu otherwise)
    chx, chy = 148, y + 280
    d.line([(chx, chy), (chx + 5, chy + 8)], fill=GREEN, width=3)
    d.line([(chx + 5, chy + 8), (chx + 17, chy - 5)], fill=GREEN, width=3)
    DRAWN.append(("uri-check", chx - 4, chy - 9, chx + 22, chy + 13))
    txt(d, chx + 26, y + 280, 'gs://nodus-media-demo/production/shoot_day_brief.md [mock]',
        F_MONO, GREEN, label="uri")
    txt(d, W / 2, y + 420,
        "mock-first: no credentials needed — the real SDK path activates with NODUS_GCLOUD=real",
        F_SUB, INK_MUTED, label="mocknote", anchor="mm")
    return img


def build_grafana_map(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "GRAFANA CLOUD  ·  every event → a live annotation", "segment 5", W)
    kinds = [
        ("task",        "nodus:task"),
        ("plan",        "nodus:plan"),
        ("tool_call",   "nodus:tool_call"),
        ("tool_result", "nodus:tool_result"),
        ("result",      "nodus:result"),
    ]
    hues = [C_TASK, C_PLAN, C_CALL, C_RES, C_RES]
    ey = y + 70
    for i, (kind, tag) in enumerate(kinds):
        rowy = ey + i * 52
        txt(d, 150, rowy, kind, F_SUB_B, INK, label=f"kind:{i}", anchor="lm")
        arrow(d, 320, 430, rowy)
        txt(d, 440, rowy, f"create_annotation · {tag}", F_MONO, GRAFANA, label=f"map:{i}", anchor="lm")
    txt(d, 150, ey + 5 * 52 + 18,
        "streamed through the official mcp-grafana server → your dashboard",
        F_TINY, INK_MUTED, label="note")
    return img


def build_repo(W, H):
    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)
    y = header(d, "OPEN SOURCE  ·  MIT", "segment 6", W)
    txt(d, W / 2, y + 130, "github.com/Rua987/nodus", F_XL, INK, label="repo", anchor="mm")
    txt(d, W / 2, y + 220, "119/120 · 99%", F_BIG, C_TASK, label="headline", anchor="mm")
    rr(d, [W / 2 - 150, y + 290, W / 2 + 150, y + 390], 12, fill=SURFACE, outline=BORDER)
    txt(d, W / 2, y + 340, "MIT LICENSE", F_SUB_B, GREEN, label="mit", anchor="mm")
    txt(d, W / 2, y + 450,
        "994 tests passing · checkpoint you can drop in and run on a laptop CPU",
        F_SUB_B, INK_SOFT, label="tests", anchor="mm")
    txt(d, W / 2, y + 500,
        "clone the repo — and let it think.",
        F_SUB, INK_MUTED, label="closing", anchor="mm")
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="video_cards")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any drawn boxes overlap")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    cards = [
        ("titre_card.png",        1920, 1080, build_titre),
        ("task_card.png",         1600, 900, build_task),
        ("modele_card.png",       1600, 900, build_modele),
        ("plan_card.png",         1600, 900, build_plan),
        ("metrics_card.png",      1600, 900, build_metrics),
        ("signtest_card.png",     1600, 900, build_signtest),
        ("wiring_gcs_card.png",   1600, 900, build_wiring_gcs),
        ("grafana_map_card.png",  1600, 900, build_grafana_map),
        ("repo_card.png",         1600, 900, build_repo),
    ]
    any_bad = False
    for name, w, h, builder in cards:
        img = builder(w, h)
        bad = save_card(img, out / name, name, w, h)
        any_bad = any_bad or bool(bad)
    print(f"\n{len(cards)} cards -> {out}/")
    if any_bad and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
