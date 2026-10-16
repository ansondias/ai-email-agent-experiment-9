"""Terminal output: a readable trace of what the agent is doing at each step."""
from __future__ import annotations

import os
import sys
import textwrap

_COLOR = sys.stdout.isatty() or bool(os.environ.get("FORCE_COLOR"))

BOLD, DIM = "1", "2"
RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN = "31", "32", "33", "34", "35", "36"


def c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def banner(model: str, confirm: bool, dry_run: bool, sender: str) -> None:
    mode = "confirm before send" if confirm else "AUTO-SEND (no confirmation)"
    print(c(BOLD, "AI Email Agent") + c(DIM, "  ·  Experiment 9  ·  LLM + Memory + Tools + Orchestration"))
    print(c(DIM, f"LLM: {model} (Ollama, local)   Sender: {sender}   Mode: {mode}"
                 f"{'   [DRY RUN]' if dry_run else ''}"))
    print()


def user(text: str) -> None:
    print(c(BOLD + ";" + BLUE, "You ▸ ") + text)


def step(tag: str, color: str, msg: str) -> None:
    print("   " + c(color + ";" + BOLD, f"[{tag}]".ljust(12)) + " " + msg)


def detail(msg: str, color: str = DIM) -> None:
    for line in msg.splitlines() or [""]:
        print(" " * 16 + c(color, line))


def understand(a: dict) -> None:
    step("UNDERSTAND", MAGENTA,
         f"intent={c(BOLD, a.get('intent', '?'))}  recipients={a.get('recipients', [])}  "
         f"tone={a.get('tone', '?')}")
    if a.get("subject"):
        detail(f"subject ≈ \"{a['subject']}\"")
    if a.get("key_points"):
        detail(f"key points: {a['key_points']}")
    if a.get("refers_to_previous_email"):
        detail("refers to a previous email → will use memory")


def tool_call(name: str, args: dict) -> None:
    shown = {k: (v if len(str(v)) < 60 else str(v)[:57] + "...") for k, v in args.items()}
    arg_str = ", ".join(f"{k}={v!r}" for k, v in shown.items())
    step("TOOL", CYAN, f"{name}({arg_str})")


def draft_box(sender: str, to: str, subject: str, body: str, verified_by: str) -> None:
    rule = "─" * 70
    print("   " + c(YELLOW, "┌─ DRAFT EMAIL " + rule[14:]))
    print("   " + c(YELLOW, "│ ") + c(BOLD, "From:    ") + sender)
    print("   " + c(YELLOW, "│ ") + c(BOLD, "To:      ") + to + c(GREEN, f"   ✔ verified ({verified_by})"))
    print("   " + c(YELLOW, "│ ") + c(BOLD, "Subject: ") + subject)
    print("   " + c(YELLOW, "├" + rule))
    for para in body.strip().split("\n"):
        for line in (textwrap.wrap(para, 76) or [""]):
            print("   " + c(YELLOW, "│ ") + line)
    print("   " + c(YELLOW, "└" + rule))


CONFIRM_PROMPT = "   ⚠  Sending is irreversible. Send this email? [y]es / [n]o / or type changes ▸ "


def ask_confirmation(draft: dict) -> str:
    """Interactive guardrail: a human must approve the draft."""
    try:
        return input(c(YELLOW + ";" + BOLD, CONFIRM_PROMPT)).strip()
    except EOFError:
        return "n"


def agent_reply(text: str, stats: str = "") -> None:
    print(c(BOLD + ";" + GREEN, "Agent ▸ ") + text)
    if stats:
        print(c(DIM, f"        ({stats})"))
    print()
