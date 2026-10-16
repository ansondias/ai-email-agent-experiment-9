"""Render captured terminal logs (with ANSI colours) into terminal-window PNGs.

Each log in screenshots/logs/ is the verbatim stdout of a real command run in
this project. This script only paints that text into a macOS-style terminal
window; it never changes the text. Agent logs captured without colour codes are
re-coloured with the same rules ui.py uses on a real terminal (see colorize()).

    python make_screenshots.py            # all logs -> screenshots/*.png
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
LOGS = BASE / "screenshots" / "logs"
OUT = BASE / "screenshots"

COLS = 118
SCALE = 2                        # render at 2x for crisp text in the report
FONT_PT = 12.5
MENLO = "/System/Library/Fonts/Menlo.ttc"

BG, FG, DIM = (30, 31, 36), (222, 224, 228), (140, 145, 155)
PALETTE = {31: (255, 110, 103), 32: (95, 215, 120), 33: (240, 200, 90),
           34: (110, 165, 255), 35: (215, 140, 255), 36: (90, 210, 225)}
SGR = re.compile(r"\x1b\[([0-9;]*)m")


def parse(line: str):
    """Split a line into (char, colour, bold) cells following SGR escape codes."""
    cells, color, bold, dim = [], None, False, False
    pos = 0
    for m in list(SGR.finditer(line)) + [None]:
        end = m.start() if m else len(line)
        for ch in line[pos:end]:
            fg = PALETTE.get(color, FG)
            if dim and color is None:
                fg = DIM
            cells.append((ch, fg, bold))
        if m is None:
            break
        pos = m.end()
        for code in (m.group(1) or "0").split(";"):
            code = int(code or 0)
            if code == 0:
                color, bold, dim = None, False, False
            elif code == 1:
                bold = True
            elif code == 2:
                dim = True
            elif 30 <= code <= 37:
                color = code
    return cells


E = "\x1b["
TAG_COLOR = {"UNDERSTAND": "35", "TOOL": "36", "DRAFT": "34", "GUARDRAIL": "33",
             "SEND": "32", "MEMORY": "35"}


def colorize(line: str) -> str:
    """Re-apply ui.py's colour scheme to an agent line that was logged without colour."""
    if "\x1b" in line:
        return line
    paint = lambda code, t: f"{E}{code}m{t}{E}0m"  # noqa: E731
    if line.startswith("AI Email Agent"):
        return paint("1", "AI Email Agent") + paint("2", line[len("AI Email Agent"):])
    if line.startswith("LLM: "):
        return paint("2", line)
    for who, code in (("You ▸ ", "1;34"), ("Agent ▸ ", "1;32")):
        if line.startswith(who):
            return paint(code, who) + line[len(who):]
    if line.startswith("   [") and "]" in line[:16]:
        tag = line[4:line.index("]")]
        code = TAG_COLOR.get(tag, "0")
        if "✖" in line:
            code = "31"
        return "   " + paint(code + ";1", line[3:15]) + line[15:]
    if line.startswith(" " * 16):
        body = line.strip()
        code = ("32" if body.startswith(("→ FOUND", "→ SAVED", "→ #")) else
                "31" if body.startswith(("→ NOT FOUND", "→ REFUSED")) else
                "33" if body.startswith(("→ AMBIGUOUS", "→ memory is empty")) else "2")
        return paint(code, line)
    if line.startswith("        (") and line.endswith(")"):
        return paint("2", line)
    if line.startswith("   ⚠"):
        head, _, ans = line.rpartition("▸ ")
        return paint("33;1", head + "▸ ") + paint("1", ans)
    if line.startswith(("   ┌", "   ├", "   └")):
        return paint("33", line)
    if line.startswith("   │ "):
        rest = line[5:]
        for label in ("From:    ", "To:      ", "Subject: "):
            if rest.startswith(label):
                rest = paint("1", label) + rest[len(label):]
                break
        if "   ✔ verified" in rest:
            a, b = rest.split("   ✔ verified", 1)
            rest = a + paint("32", "   ✔ verified" + b)
        return paint("33", "   │ ") + rest
    return line


def wrap(cells):
    rows = [cells[i:i + COLS] for i in range(0, len(cells), COLS)]
    return rows or [[]]


def render(log: Path, title: str) -> Path:
    text = log.read_text(errors="replace").expandtabs(8).rstrip("\n")
    is_agent_log = "AI Email Agent" in text          # only agent output gets ui.py colours
    rows = [r for line in text.split("\n")
            for r in wrap(parse(colorize(line) if is_agent_log else line))]

    fsize = int(FONT_PT * SCALE)
    regular = ImageFont.truetype(MENLO, fsize, index=0)
    bold = ImageFont.truetype(MENLO, fsize, index=1)
    cw = regular.getlength("M")
    lh = int(fsize * 1.24)
    pad, bar = 16 * SCALE, 30 * SCALE

    width = int(COLS * cw + 2 * pad)
    height = bar + pad + lh * len(rows) + pad
    img = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(img)

    # title bar + traffic lights
    d.rectangle([0, 0, width, bar], fill=(52, 54, 60))
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx, cy, r = pad + i * 22 * SCALE, bar // 2, 6 * SCALE
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    tf = ImageFont.truetype(MENLO, int(11 * SCALE))
    d.text(((width - d.textlength(title, font=tf)) / 2, bar / 2), title,
           font=tf, fill=(200, 202, 208), anchor="lm")

    y = bar + pad
    for row in rows:
        x = pad
        for ch, fg, is_bold in row:
            font = bold if is_bold else regular
            d.text((x, y), ch, font=font, fill=fg)
            x += cw
        y += lh

    out = OUT / (log.stem + ".png")
    img.save(out, optimize=True)
    return out


if __name__ == "__main__":
    names = sys.argv[1:] or [p.stem for p in sorted(LOGS.glob("*.log"))]
    for name in names:
        print(render(LOGS / f"{name}.log", "ansondias — experiment-9-email-agent — zsh"))
