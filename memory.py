"""Agent memory.

* Short-term memory: the recent conversation turns, replayed to the LLM on every
  request so follow-ups ("send the same email to me too") need no re-explaining.
* Long-term memory: every drafted / sent / declined email, persisted to JSON so
  it survives restarts of the program.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class Memory:
    def __init__(self, path: Path, short_term_turns: int = 12):
        self.path = path
        self.short_term_turns = short_term_turns
        data = json.loads(path.read_text()) if path.exists() else {}
        self.turns: List[Dict] = data.get("turns", [])
        self.emails: List[Dict] = data.get("emails", [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"turns": self.turns, "emails": self.emails},
                                        indent=2, ensure_ascii=False) + "\n")

    # ---- short-term -------------------------------------------------------
    def add_turn(self, role: str, text: str) -> None:
        self.turns.append({"role": role, "content": text,
                           "time": datetime.now().isoformat(timespec="seconds")})
        self.save()

    def recent_turns(self) -> List[Dict]:
        return [{"role": t["role"], "content": t["content"]}
                for t in self.turns[-self.short_term_turns:]]

    def user_texts(self) -> List[str]:
        return [t["content"] for t in self.turns if t["role"] == "user"]

    # ---- long-term --------------------------------------------------------
    def record_email(self, to_name: str, to_email: str, subject: str, body: str,
                     status: str, message_id: Optional[str] = None) -> Dict:
        entry = {"id": len(self.emails) + 1,
                 "time": datetime.now().isoformat(timespec="seconds"),
                 "status": status, "to_name": to_name, "to_email": to_email,
                 "subject": subject, "body": body, "message_id": message_id}
        self.emails.append(entry)
        self.save()
        return entry

    def recent_emails(self, n: int = 3) -> List[Dict]:
        return list(reversed(self.emails[-n:]))

    def summary(self) -> str:
        if not self.emails:
            return "no emails have been drafted or sent yet."
        counts = {}
        for e in self.emails:
            counts[e["status"]] = counts.get(e["status"], 0) + 1
        detail = ", ".join(f"{v} {k.lower()}" for k, v in counts.items())
        return f"{len(self.emails)} emails on record ({detail})."
