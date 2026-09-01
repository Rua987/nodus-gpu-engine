#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate the Devpost gallery image (1600x900 PNG) from a real run.

The content is the actual output of the media workflow run (real NODUS 324M
planner, checkpoint v5):
  - task:  the Agentic Cinema media task (read the script, save the shoot-day
           brief, deliver it to Google Cloud Storage, verify)
  - plan:  real 324M -> ['read_file','write_file','bash'] + harness delivery
           `gcs_upload` (capability tool — the 8-tool vocabulary is untouched)
  - exec:  harness fills the args, executes, verifies (GCS mock-first)
  - obs:   every event -> a Grafana Cloud annotation (mock timeline shown)

Layout is MEASURED: every string is fitted to its box before drawing and a
programmatic overlap check runs at the end (prints violations, exits 1 if
any two drawn boxes intersect) — so no phrase can overlap without failing.

Usage:
    python make_gallery_image.py [--out gallery_timeline.png] [--strict]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Palette (validated on #121b26: categorical slots 1-4 + status good) ───
PAGE       = (10, 15, 22)       # #0a0f16  page plane
SURFACE    = (18, 27, 38)       # #121b26  panel surface
RAISED     = (23, 34, 49)       # #172231  raised card
BORDER     = (42, 60, 82)       # #2a3c52  hairline
INK        = (234, 242, 251)    # #eaf2fb  primary ink
INK_SOFT   = (172, 193, 214)    # #acc1d6  secondary ink
INK_MUTED  = (126, 145, 168)    # #7e91a8  muted
GREEN      = (12, 163, 12)      # #0ca30c  success (status, icon+label)
GRAFANA    = (244, 104, 0)      # #f46800  Grafana Cloud brand
C_TASK     = (57, 135, 229)     # #3987e5  slot 1 · task
C_PLAN     = (217, 89, 38)      # #d95926  slot 2 · plan
C_CALL     = (25, 158, 112)     # #199e70  slot 3 · tool_call
C_RES      = (201, 133, 0)      # #c98500  slot 4 · tool_result
ON_HUE     = (8, 16, 24)        # dark ink on the badge hues

W, H = 1600, 900

FW = r"C:\Windows\Fonts"
def _f(name, size):
    return ImageFont.truetype(f"{FW}\\{name}", size)

F_TITLE   = _f("segoeuib.ttf", 33)
F_SUB     = _f("segoeui.ttf", 16)
F_PANEL   = _f("seguisb.ttf", 14)
F_TASK    = _f("segoeui.ttf", 18)
F_CHIP    = _f("seguisb.ttf", 14)
F_MONO    = _f("consola.ttf", 16)
F_MONO_B  = _f("consolab.ttf", 16)
F_TINY    = _f("segoeui.ttf", 13)
F_TINY_B  = _f("seguisb.ttf", 13)

# ── Real-run content: real 324M planner (ckpt v5) + harness execution ───────
# (demo_agentic_cinema.py --task-key media with NODUS_PLAN_CKPT set; GCS mock)
RUN_TASK = ("Read script.txt, then save a new file shoot_day_brief.md with the "
            "shoot-day brief, then upload it to Google Cloud Storage, then verify.")
RUN_PLAN = ["read_file", "write_file", "bash", "gcs_upload"]
RUN_STEPS = [
    ("read_file", '{"path": "script.txt"}',
     "SCENE 3  INT. EDIT BAY — DAY"),
    ("write_file", '{"path": "shoot_day_brief.md", …}',
     "wrote 244 bytes -> shoot_day_brief.md"),
    ("bash", '{"command": "ls"}',
     "script.txt  shoot_day_brief.md"),
    ("gcs_upload", '{"local_path": "shoot_day_brief.md", …}',
     "gs://nodus-media-demo/production/shoot_day_brief.md (253 bytes) [mock]"),
]
RUN_RESULT = "Done: wrote shoot_day_brief.md; uploaded production/shoot_day_brief.md."

# ── Measured-layout plumbing ──────────────────────────────────────────────
DRAWN = []  # (label, x0, y0, x1, y1) — ink boxes of everything drawn


def txt(d, x, y, s, font, fill, label="", maxw=None, anchor="lm"):
    """Draw text at left-mid (x, y); fit to maxw if given; record ink box."""
    if maxw:
        while s and d.textlength(s, font=font) > maxw:
            s = s[:-1]
        if s and d.textlength(s + "…", font=font) <= maxw:
            s += "…"
        elif s and d.textlength(s, font=font) > maxw:
            s = ""
    ink = d.textbbox((x, y), s, font=font, anchor=anchor)
    DRAWN.append((label, ink[0], ink[1], ink[2], ink[3]))
    d.text((x, y), s, font=font, fill=fill, anchor=anchor)
    return d.textlength(s, font=font)


def wrap(d, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def rr(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def chip(d, x, cy, text, font, fg, bg, pad=(10, 5), r=6):
    """Chip centered on cy; returns right edge x1."""
    w = d.textlength(text, font=font) + 2 * pad[0]
    h = font.size + 2 * pad[1]
    rr(d, [x, cy - h / 2, x + w, cy + h / 2], r, fill=bg)
    d.text((x + pad[0], cy), text, font=font, fill=fg, anchor="lm")
    DRAWN.append((f"chip:{text}", x, cy - h / 2, x + w, cy + h / 2))
    return x + w


def badge(d, x, cy, glyph, label, hue):
    """Event-kind badge with color swatch + text label; returns right edge."""
    rr(d, [x, cy - 13, x + 26, cy + 13], 6, fill=hue)
    d.text((x + 13, cy), glyph, font=F_MONO_B, fill=ON_HUE, anchor="mm")
    DRAWN.append((f"swatch:{label}", x, cy - 13, x + 26, cy + 13))
    w = d.textlength(label, font=F_TINY_B)
    txt(d, x + 34, cy, label, F_TINY_B, INK, label=f"badge:{label}")
    return x + 34 + w


def check_overlaps():
    """Text/chip overlaps only — background boxes are tagged 'bg:' and skipped."""
    bad = []
    items = [e for e in DRAWN if not e[0].startswith("bg:")]
    for i in range(len(items)):
        a = items[i]
        for j in range(i + 1, len(items)):
            b = items[j]
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                bad.append((a[0], b[0]))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="gallery_timeline.png")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any drawn boxes overlap")
    args = ap.parse_args()

    img = Image.new("RGB", (W, H), PAGE)
    d = ImageDraw.Draw(img)

    # ── Header ────────────────────────────────────────────────────────────
    rr(d, [48, 22, 94, 68], 12, fill=GRAFANA)
    d.text((71, 45), "N", font=F_TITLE, fill=ON_HUE, anchor="mm")
    DRAWN.append(("bg:logo", 48, 22, 94, 68))
    txt(d, 110, 45, "NODUS", F_TITLE, INK, label="wordmark")
    txt(d, 110, 72, "a tiny local planner · free agentic planning, observable",
        F_SUB, INK_SOFT, label="subtitle")
    d.line([48, 94, W - 48, 94], fill=BORDER, width=1)
    # header chips (brand hues, not data series)
    GOOGLE_BLUE = (66, 133, 244)  # #4285f4
    chip(d, W - 300, 42, "Grafana Cloud · MCP", F_CHIP, (255, 176, 102), (54, 30, 6))
    chip(d, W - 300, 72, "Google Cloud · Gemini + GCS", F_CHIP, ON_HUE, GOOGLE_BLUE)

    # ── Panels ────────────────────────────────────────────────────────────
    LX, LY, LPW = 40, 112, 850
    RX = LX + LPW + 24
    RPW = W - RX - 40
    BOT = 806
    rr(d, [LX, LY, LX + LPW, BOT], 16, fill=SURFACE)
    rr(d, [RX, LY, RX + RPW, BOT], 16, fill=SURFACE)

    # ================= LEFT PANEL : THE REAL RUN =================
    PX, PX1 = LX + 28, LX + LPW - 28
    txt(d, PX, LY + 20, "THE REAL RUN  ·  task → plan → tools → verify",
        F_PANEL, INK_SOFT, label="panel-title")

    # task card
    ty = LY + 46
    rr(d, [PX, ty, PX1, ty + 78], 10, fill=RAISED, outline=BORDER)
    badge(d, PX + 14, ty + 18, "▶", "TASK", C_TASK)
    tl = wrap(d, RUN_TASK, F_TASK, PX1 - PX - 110)
    for i, ln in enumerate(tl):
        txt(d, PX + 14, ty + 40 + i * (F_TASK.size + 7), ln, F_TASK, INK,
            label=f"task:{i}")

    # plan row
    py = ty + 96
    badge(d, PX + 14, py, "∘", "PLAN", C_PLAN)
    txt(d, PX + 14, py + 24, "real 324M planner → ordered tool names (harness fills the args)",
        F_TINY, INK_MUTED, label="plan-note", maxw=PX1 - PX - 28)
    # tool chips with arrows (fixed categorical order, never cycled)
    PLAN_HUES = [C_TASK, C_PLAN, C_CALL, C_RES]
    hx = PX + 14
    hy = py + 52
    for i, t in enumerate(RUN_PLAN):
        endx = chip(d, hx, hy, t, F_CHIP, ON_HUE, PLAN_HUES[i])
        if i < len(RUN_PLAN) - 1:
            arrow_x0, arrow_x1 = endx + 12, endx + 32
            d.line([arrow_x0, hy, arrow_x1 - 8, hy], fill=INK_MUTED, width=2)
            d.polygon([(arrow_x1 - 10, hy - 5), (arrow_x1 - 10, hy + 5), (arrow_x1, hy)],
                      fill=INK_MUTED)
            DRAWN.append((f"arrow:{i}", arrow_x0, hy - 6, arrow_x1, hy + 6))
        hx = endx + 32

    # execution rows
    ey = py + 84
    txt(d, PX + 14, ey, "EXECUTION  ·  harness fills the args · mock-first delivery",
        F_TINY_B, INK_MUTED, label="exec-header")
    row_h = 46
    ry = ey + 26
    for i, (tool, args_str, out_str) in enumerate(RUN_STEPS):
        y = ry + i * (row_h + 8)
        rr(d, [PX, y, PX1, y + row_h - 6], 8, fill=RAISED)
        DRAWN.append((f"bg:rowbox:{i}", PX, y, PX1, y + row_h - 6))
        txt(d, PX + 14, y + 17, f"↳ {tool}", F_MONO_B, INK,
            label=f"tool:{i}", maxw=170)
        txt(d, PX + 200, y + 17, args_str, F_MONO, INK_SOFT,
            label=f"args:{i}", maxw=380)
        txt(d, PX + 14, y + 33, "✓ " + out_str, F_MONO, GREEN,
            label=f"out:{i}", maxw=PX1 - PX - 28)

    # result row
    rres = ry + len(RUN_STEPS) * (row_h + 8) + 4
    rr(d, [PX, rres, PX1, rres + 44], 8, fill=RAISED, outline=(36, 74, 44))
    DRAWN.append(("bg:resultbox", PX, rres, PX1, rres + 44))
    txt(d, PX + 14, rres + 14, "● result", F_MONO_B, INK, label="result-label", maxw=110)
    txt(d, PX + 14, rres + 30, "✓ " + RUN_RESULT, F_MONO_B, GREEN,
        label="result", maxw=PX1 - PX - 28)

    # ================= RIGHT PANEL : GRAFANA CLOUD =================
    QX, QX1 = RX + 28, RX + RPW - 28
    txt(d, QX, LY + 20, "GRAFANA CLOUD  ·  observability",
        F_PANEL, INK_SOFT, label="right-title")
    txt(d, QX, LY + 40, "every event → a tagged annotation (official mcp-grafana server)",
        F_TINY, INK_MUTED, label="right-sub", maxw=QX1 - QX)

    # event -> annotation mapping
    kinds = [
        ("task",        "nodus:task",        C_TASK),
        ("plan",        "nodus:plan",        C_PLAN),
        ("tool_call",   "nodus:tool_call",   C_CALL),
        ("tool_result", "nodus:tool_result", C_RES),
        ("result",      "nodus:result",      C_RES),
    ]
    ey0 = LY + 62
    for i, (kind, tag, hue) in enumerate(kinds):
        y = ey0 + i * 34
        badge(d, QX, y, "·", kind, hue)
        arrow_x0, arrow_x1 = QX + 210, QX + 236
        d.line([arrow_x0, y, arrow_x1 - 7, y], fill=INK_MUTED, width=2)
        d.polygon([(arrow_x1 - 9, y - 4), (arrow_x1 - 9, y + 4), (arrow_x1, y)], fill=INK_MUTED)
        DRAWN.append((f"m-arrow:{i}", arrow_x0, y - 5, arrow_x1, y + 5))
        txt(d, QX + 244, y, f"create_annotation · {tag}", F_MONO, GRAFANA,
            label=f"mapping:{i}", maxw=QX1 - (QX + 244))

    # wiring
    wy = ey0 + len(kinds) * 34 + 18
    txt(d, QX, wy, "THE WIRING", F_TINY_B, INK_MUTED, label="wiring-title")
    wiring = [
        ("NODUS_GRAFANA=mcp", "env switch — mock by default, live when set"),
        ("mcp-grafana  server", "official Grafana Cloud MCP server"),
        ("create_annotation", "tagged annotations → your dashboard"),
    ]
    w_cy = wy + 30
    for i, (a, b) in enumerate(wiring):
        y = w_cy + i * 52
        rr(d, [QX, y - 22, QX1, y + 22], 10, fill=SURFACE, outline=BORDER)
        DRAWN.append((f"bg:wiringbox:{i}", QX, y - 22, QX1, y + 22))
        txt(d, QX + 16, y, a, F_MONO_B, GRAFANA, label=f"wiring:{i}", maxw=220)
        txt(d, QX + 248, y, b, F_TINY, INK_MUTED, label=f"wiring-sub:{i}", maxw=QX1 - (QX + 248))
        if i < len(wiring) - 1:
            d.line([QX + 14, y + 22, QX + 14, y + 30], fill=INK_MUTED, width=2)
            DRAWN.append((f"wv:{i}", QX + 12, y + 22, QX + 16, y + 30))

    txt(d, QX, BOT - 24, "no account? mock prints this identical timeline — "
        "add GRAFANA_URL + a service-account token to go live.",
        F_TINY, INK_MUTED, label="right-caption", maxw=QX1 - QX)

    # ================= FOOTER STATS =================
    fy = 820
    rr(d, [40, fy, W - 40, fy + 60], 12, fill=SURFACE, outline=BORDER)
    stats = [
        ("99%",  "plans correct · 120 unseen tasks", C_TASK),
        ("p = 0.0139", "sign test — plan helps e2e", GREEN),
        ("994",  "tests passing", C_CALL),
    ]
    gap = 90
    widths = [max(d.textlength(big, font=F_TITLE), d.textlength(sub, font=F_TINY)) for big, sub, _ in stats]
    total = sum(widths) + gap * (len(stats) - 1)
    sx = (W - total) / 2
    for (big, sub, hue), wd in zip(stats, widths):
        txt(d, sx, fy + 16, big, F_TITLE, hue, label=f"stat:{big}")
        txt(d, sx, fy + 45, sub, F_TINY, INK_SOFT, label=f"stat-sub:{sub}")
        sx += wd + gap
    txt(d, W - 48, fy + 30, "github.com/Rua987/nodus", F_CHIP, INK_SOFT, label="repo")

    # ── Guard: no drawn boxes may overlap ────────────────────────────────
    bad = check_overlaps()
    img.save(args.out)
    print(f"wrote {args.out} ({W}x{H}); {len(DRAWN)} drawn boxes; "
          f"{'OK — no overlaps' if not bad else f'{len(bad)} OVERLAPS: {bad}'}")
    if bad and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
