"""Draw the agent architecture figure (screenshots/00_architecture.png) with Pillow."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2  # render scale
W, H = 1600, 930
OUT = Path(__file__).resolve().parent / "screenshots" / "00_architecture.png"
UNI = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

img = Image.new("RGB", (W * S, H * S), "white")
d = ImageDraw.Draw(img)
f_title = ImageFont.truetype(BOLD, 19 * S)
f_body = ImageFont.truetype(UNI, 15 * S)

THEME = {  # fill, border
    "llm": ((238, 230, 255), (120, 80, 200)),
    "orch": ((225, 238, 255), (50, 110, 200)),
    "tools": ((222, 246, 244), (30, 140, 130)),
    "guard": ((255, 241, 220), (215, 120, 20)),
    "mem": ((228, 245, 228), (60, 150, 70)),
    "io": ((240, 240, 242), (110, 110, 120)),
}


def box(x1, y1, x2, y2, kind, title, lines=()):
    fill, edge = THEME[kind]
    d.rounded_rectangle([x1 * S, y1 * S, x2 * S, y2 * S], radius=12 * S, fill=fill, outline=edge, width=2 * S)
    y = y1 + 14
    d.text(((x1 + x2) / 2 * S, y * S), title, font=f_title, fill=edge, anchor="mt")
    y += 30
    for line in lines:
        d.text(((x1 + x2) / 2 * S, y * S), line, font=f_body, fill=(40, 40, 50), anchor="mt")
        y += 22


def arrow(x1, y1, x2, y2, color=(80, 80, 90), both=False, dashed=False):
    import math
    if dashed:
        n = int(math.hypot(x2 - x1, y2 - y1) // 12)
        for i in range(0, n, 2):
            a, b = i / n, min((i + 1) / n, 1)
            d.line([(x1 + (x2 - x1) * a) * S, (y1 + (y2 - y1) * a) * S,
                    (x1 + (x2 - x1) * b) * S, (y1 + (y2 - y1) * b) * S], fill=color, width=2 * S)
    else:
        d.line([x1 * S, y1 * S, x2 * S, y2 * S], fill=color, width=2 * S)

    def head(xa, ya, xb, yb):
        ang = math.atan2(yb - ya, xb - xa)
        pts = [(xb, yb), (xb - 13 * math.cos(ang - 0.4), yb - 13 * math.sin(ang - 0.4)),
               (xb - 13 * math.cos(ang + 0.4), yb - 13 * math.sin(ang + 0.4))]
        d.polygon([(px * S, py * S) for px, py in pts], fill=color)
    head(x1, y1, x2, y2)
    if both:
        head(x2, y2, x1, y1)


def label(x, y, text):
    d.text((x * S, y * S), text, font=f_body, fill=(90, 90, 100), anchor="mm")


# top: the LLM
box(330, 20, 1170, 100, "llm", "LLM  —  Qwen2.5-7B-Instruct via Ollama (local, temperature 0)",
    ["reasoning · planning · tool selection · drafting"])
# middle row: the orchestration pipeline
box(30, 170, 270, 290, "io", "User", ["natural-language", "instruction"])
box(330, 160, 680, 300, "orch", "1. UNDERSTAND", ["JSON-schema output:", "intent · recipients · subject", "key points · tone"])
box(740, 160, 1170, 300, "orch", "2. PLAN / ACT  (ReAct loop)", ["LLM picks a tool → code runs it", "→ observation fed back", "max 8 steps · stall recovery"])
box(1230, 170, 1570, 290, "io", "6. Reply to user", ["\"Sent your email to …\"", "+ time / call stats"])
arrow(270, 230, 330, 230)
arrow(680, 230, 740, 230)
arrow(1170, 230, 1230, 230)
arrow(505, 100, 505, 160, (120, 80, 200), both=True, dashed=True)
arrow(955, 100, 955, 160, (120, 80, 200), both=True, dashed=True)

# tools
box(700, 380, 1210, 540, "tools", "TOOLS  (tools.py)",
    ["lookup_contact(name)          save_contact(name, email)",
     "recall_recent_emails(count)",
     "send_email(to, subject, body)    resend_email(id, to)"])
arrow(955, 300, 955, 380, (30, 140, 130), both=True)
label(1030, 340, "tool calls / results")

# guardrails + send
box(700, 620, 1210, 800, "guard", "3-4. DRAFT + GUARDRAILS  (enforced in code)",
    ["① address must be in contacts or typed by the user",
     "② full draft shown → human answers y / n / edit",
     "③ no duplicate send · no retry after \"no\"",
     "→ BLOCKED / NOT_SENT returned to the LLM"])
arrow(955, 540, 955, 620, (215, 120, 20))
box(1270, 640, 1570, 780, "io", "5. SEND", ["smtplib over SSL", "smtp.gmail.com:465", "16-char App Password"])
arrow(1210, 710, 1270, 710, (215, 120, 20))
box(1270, 830, 1570, 900, "io", "Recipient inbox")
arrow(1420, 780, 1420, 830)

# memory + contacts
box(30, 380, 600, 540, "mem", "MEMORY  (memory.py → data/memory.json)",
    ["short-term: last 12 conversation turns replayed",
     "long-term: every email (SENT / DECLINED / FAILED)",
     "survives restarts → \"send the same email to me too\""])
box(30, 620, 600, 780, "mem", "CONTACTS  (data/contacts.json)",
    ["the ONLY source of email addresses",
     "name · alias · title-insensitive · fuzzy match",
     "new contacts saved only if the user typed them"])
arrow(600, 460, 700, 460, (60, 150, 70), both=True)
label(650, 440, "recall")
label(650, 482, "record")
arrow(600, 640, 700, 530, (60, 150, 70), both=True)
label(548, 584, "lookup / save")
arrow(600, 720, 700, 720, (215, 120, 20), both=True)
label(650, 742, "verify")
arrow(150, 290, 150, 380, (60, 150, 70), both=True)
label(205, 335, "turns")

d.text((30 * S, 905 * S), "Orchestration = agent.py · LLM = llm.py · Tools = tools.py · Memory = memory.py",
       font=f_body, fill=(120, 120, 130), anchor="lm")
img.save(OUT, optimize=True)
print(OUT)
