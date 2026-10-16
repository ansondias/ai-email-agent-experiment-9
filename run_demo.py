"""Scripted demo of the agent, one scenario per process (used for the report).

    python run_demo.py 1   # new email to Dr. Meher (lookup -> draft -> confirm -> send)
    python run_demo.py 2   # "Send the same email to me too"  (memory, new process)
    python run_demo.py 3   # John is not in contacts -> agent asks -> user declines
    python run_demo.py 4   # "What emails have I sent so far?" (long-term memory)

The instructions and the human's confirmation answers are scripted. Safety: in a
live run a "y" is only given if the exact draft (recipient + subject + body)
appears in approved_drafts.json, which the human fills in after reviewing the
dry-run drafts. Any other draft is answered "n" and nothing is sent.
"""
from __future__ import annotations

import hashlib
import json
import sys

import config
import ui
from agent import EmailAgent

SCENARIOS = {
    1: [("Send an email to Dr. Meher saying that my Experiment 9 AI Email Agent is complete. "
         "It understands instructions with a local LLM, looks up contacts, drafts the email, "
         "asks for confirmation before sending and remembers past interactions. Mention that "
         "this email itself was drafted and sent by the agent. Keep it formal.", ["y"])],
    2: [("Send the same email to me too.", ["y"])],
    3: [("Email John a reminder about tomorrow's 10 AM project meeting.", []),
        ("It's john.doe@example.com", ["n"])],
    4: [("What emails have I sent so far?", [])],
}

APPROVED = config.DATA_DIR / "approved_drafts.json"
SEEN = config.DATA_DIR / "drafts_seen.json"


def draft_hash(d: dict) -> str:
    raw = "\x1f".join([d["to_email"].lower(), d["subject"], d["body"]])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load(path):
    return json.loads(path.read_text()) if path.exists() else []


def main(n: int) -> None:
    ui.banner(config.MODEL, config.CONFIRM_BEFORE_SEND, config.DRY_RUN, config.GMAIL_ADDRESS)
    answers: list = []

    def scripted_confirm(draft: dict) -> str:
        planned = answers.pop(0) if answers else "n"
        h = draft_hash(draft)
        seen = [s for s in load(SEEN) if s["hash"] != h] + [{"hash": h, **draft}]
        SEEN.write_text(json.dumps(seen, indent=2, ensure_ascii=False) + "\n")
        if planned == "y" and not config.DRY_RUN and h not in load(APPROVED):
            print(ui.c(ui.RED, f"   (draft {h} was not pre-approved by the user -> answering n)"))
            planned = "n"
        print(ui.c(ui.YELLOW + ";" + ui.BOLD, ui.CONFIRM_PROMPT) + ui.c(ui.BOLD, planned))
        return planned

    agent = EmailAgent(confirm_fn=scripted_confirm)
    for text, confirm_answers in SCENARIOS[n]:
        answers[:] = confirm_answers
        ui.user(text)
        agent.handle(text)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
