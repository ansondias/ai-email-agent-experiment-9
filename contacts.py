"""Contacts store — the only source of truth for email addresses.

The agent must never invent an address: it either finds the person here or asks
the user, and a user-supplied address is saved here for next time.
"""
from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Dict, List

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TITLES = {"dr", "prof", "professor", "mr", "mrs", "ms", "miss", "sir", "madam"}


def normalise(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _TITLES)


class ContactStore:
    def __init__(self, path: Path):
        self.path = path
        self.contacts: List[Dict] = json.loads(path.read_text()) if path.exists() else []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.contacts, indent=2) + "\n")

    def all_emails(self) -> set:
        return {c["email"].lower() for c in self.contacts}

    def lookup(self, name: str) -> List[Dict]:
        """Exact name/alias match first, then word overlap, then fuzzy spelling."""
        query = normalise(name)
        if not query:
            return []
        if EMAIL_RE.fullmatch(name.strip()):
            return [c for c in self.contacts if c["email"].lower() == name.strip().lower()]

        def keys(c):
            return [normalise(c["name"])] + [normalise(a) for a in c.get("aliases", [])]

        exact = [c for c in self.contacts if query in keys(c)]
        if exact:
            return exact
        qwords = set(query.split())
        overlap = [c for c in self.contacts
                   if any(qwords & set(k.split()) for k in keys(c))]
        if overlap:
            return overlap
        return [c for c in self.contacts
                if any(difflib.SequenceMatcher(None, query, k).ratio() >= 0.85 for k in keys(c))]

    def by_email(self, email: str):
        return next((c for c in self.contacts if c["email"].lower() == email.strip().lower()), None)

    def add(self, name: str, email: str) -> Dict:
        for c in self.contacts:
            if c["email"].lower() == email.lower():
                return c
        contact = {"name": name.strip(), "email": email.strip(), "aliases": [],
                   "relation": "added by the user during a conversation"}
        self.contacts.append(contact)
        self._save()
        return contact
