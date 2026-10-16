"""Tools the LLM can call, plus the guardrails wrapped around them.

Guardrails are enforced here in code, not left to the model:
  1. No hallucinated addresses — send_email / resend_email / save_contact only
     accept an address that is in the contacts store or was typed by the user.
  2. Human confirmation — sending is irreversible, so the draft is shown and the
     user must answer "y" (unless CONFIRM_BEFORE_SEND=false).
  3. No duplicates — the same email cannot be sent twice in one instruction, and a
     declined email is not retried.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Optional, Tuple

import config
import mailer
import ui
from contacts import EMAIL_RE, ContactStore
from memory import Memory


def _fn(name: str, description: str, props: Dict, required) -> Dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required}}}


TOOL_SCHEMAS = [
    _fn("lookup_contact",
        "Find a person's email address in the contacts store by name or alias "
        "(e.g. 'Dr. Meher', 'me'). Always call this for every recipient before emailing.",
        {"name": {"type": "string", "description": "Name as the user said it"}}, ["name"]),
    _fn("save_contact",
        "Save a new contact. Only use an email address the USER typed in the chat.",
        {"name": {"type": "string"}, "email": {"type": "string"}}, ["name", "email"]),
    _fn("recall_recent_emails",
        "Recall recently drafted/sent emails from long-term memory, newest first. "
        "Use it when the user says 'the same email', 'that email', 'resend', etc.",
        {"count": {"type": "integer", "description": "How many to return (default 1)"}}, []),
    _fn("send_email",
        "Write and send a NEW email via Gmail to ONE recipient. The draft is shown to the "
        "user, who must confirm it. Call once per recipient.",
        {"to_name": {"type": "string"}, "to_email": {"type": "string"},
         "subject": {"type": "string"},
         "body": {"type": "string", "description": "Full email body incl. greeting and sign-off"}},
        ["to_name", "to_email", "subject", "body"]),
    _fn("resend_email",
        "Send an email that is already in memory (from recall_recent_emails) to another "
        "recipient. Subject and body are reused exactly; only the greeting is adapted.",
        {"email_id": {"type": "integer", "description": "The #id from recall_recent_emails"},
         "to_name": {"type": "string"}, "to_email": {"type": "string"}},
        ["email_id", "to_name", "to_email"]),
]

ConfirmFn = Callable[[Dict], str]
_TITLES = ("dr", "prof", "mr", "mrs", "ms")


def _clean_body(body: str) -> str:
    """Drop a 'Subject: ...' line that small models sometimes repeat inside the body."""
    lines = body.strip().splitlines()
    if lines and lines[0].lower().startswith("subject:"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def _salutation_name(full_name: str) -> str:
    """'Dr. Kunal Meher' -> 'Dr. Meher', 'Anson Dias' -> 'Anson'."""
    words = full_name.split()
    if len(words) > 1 and words[0].rstrip(".").lower() in _TITLES:
        return f"{words[0]} {words[-1]}"
    return words[0] if words else full_name


def _adapt_greeting(body: str, to_name: str) -> str:
    lines = body.splitlines()
    if lines and re.match(r"^\s*(dear|hi|hello|hey)\b", lines[0], re.I):
        lines[0] = f"{lines[0].split()[0]} {_salutation_name(to_name)},"
    return "\n".join(lines)


class Toolbox:
    def __init__(self, contacts: ContactStore, memory: Memory,
                 confirm_fn: Optional[ConfirmFn] = None):
        self.contacts = contacts
        self.memory = memory
        self.confirm_fn = confirm_fn or ui.ask_confirmation
        self.sent_this_turn: set = set()
        self.declined_this_turn: set = set()

    def new_turn(self) -> None:
        self.sent_this_turn.clear()
        self.declined_this_turn.clear()

    # ---- guardrail 1: address verification ------------------------------
    def verify_address(self, email: str) -> Tuple[bool, str]:
        email = email.strip().lower()
        if email in self.contacts.all_emails():
            return True, "contact store"
        typed = {m.lower() for text in self.memory.user_texts() for m in EMAIL_RE.findall(text)}
        if email in typed:
            return True, "typed by user"
        return False, "not in contacts and never given by the user"

    # ---- dispatcher -------------------------------------------------------
    def run(self, name: str, args: Dict) -> str:
        ui.tool_call(name, args)
        handler = {"lookup_contact": self.lookup_contact, "save_contact": self.save_contact,
                   "recall_recent_emails": self.recall_recent_emails,
                   "send_email": self.send_email, "resend_email": self.resend_email}.get(name)
        if handler is None:
            return f"ERROR: unknown tool {name!r}."
        try:
            return handler(**args)
        except TypeError as exc:
            return f"ERROR: bad arguments for {name}: {exc}"

    # ---- tools --------------------------------------------------------------
    def lookup_contact(self, name: str) -> str:
        matches = self.contacts.lookup(name)
        if not matches:
            ui.detail(f"→ NOT FOUND: no contact called {name!r} (agent must ask, not guess)", ui.RED)
            return (f"NOT_FOUND: there is no contact called {name!r}. Do NOT guess an address. "
                    f"Ask the user for {name}'s email address and wait for the reply.")
        if len(matches) > 1:
            listing = "; ".join(f"{m['name']} <{m['email']}>" for m in matches)
            ui.detail(f"→ AMBIGUOUS: {listing}", ui.YELLOW)
            return f"AMBIGUOUS: several contacts match {name!r}: {listing}. Ask the user which one."
        m = matches[0]
        ui.detail(f"→ FOUND {m['name']} <{m['email']}>  ({m.get('relation', '')})", ui.GREEN)
        return f"FOUND: {m['name']} <{m['email']}> ({m.get('relation', '')})"

    def save_contact(self, name: str, email: str) -> str:
        ok, why = self.verify_address(email)
        if not EMAIL_RE.fullmatch(email.strip()) or not ok:
            ui.detail(f"→ REFUSED: {email!r} {why}", ui.RED)
            return (f"REFUSED: {email!r} was not provided by the user. "
                    "Ask the user for the exact address.")
        c = self.contacts.add(name, email)
        ui.detail(f"→ SAVED {c['name']} <{c['email']}> to {self.contacts.path.name}", ui.GREEN)
        return f"SAVED: {c['name']} <{c['email']}>"

    def recall_recent_emails(self, count: int = 1) -> str:
        emails = self.memory.recent_emails(max(1, int(count or 1)))
        if not emails:
            ui.detail("→ memory is empty", ui.YELLOW)
            return "MEMORY_EMPTY: no previous emails."
        for e in emails:
            ui.detail(f"→ #{e['id']} [{e['status']}] to {e['to_name']}: \"{e['subject']}\"", ui.GREEN)
        out = [f"Email #{e['id']} [{e['status']} at {e['time']}] to {e['to_name']} "
               f"<{e['to_email']}>\nSubject: {e['subject']}\nBody:\n{e['body']}" for e in emails]
        return ("\n\n".join(out) + f"\n\nTo send email #{emails[0]['id']} to someone else: call "
                "lookup_contact for the new recipient, then resend_email with that email_id.")

    def send_email(self, to_name: str, to_email: str, subject: str, body: str) -> str:
        body = _clean_body(body)
        return self._guarded_send(to_name, to_email, subject, body,
                                  f"LLM composed the email ({len(body.split())} words)")

    def resend_email(self, email_id: int, to_name: str, to_email: str) -> str:
        original = next((e for e in self.memory.emails if e["id"] == int(email_id)), None)
        if original is None:
            return f"ERROR: there is no email #{email_id} in memory. Call recall_recent_emails."
        contact = self.contacts.by_email(to_email)
        body = _adapt_greeting(original["body"], contact["name"] if contact else to_name)
        return self._guarded_send(to_name, to_email, original["subject"], body,
                                  f"reusing email #{original['id']} from long-term memory "
                                  "(greeting adapted)")

    # ---- the only path that can send mail ------------------------------------
    def _guarded_send(self, to_name: str, to_email: str, subject: str, body: str,
                      origin: str) -> str:
        to_email = to_email.strip()
        contact = self.contacts.by_email(to_email)
        if contact:                       # canonical name, e.g. "me" -> "Anson Dias"
            to_name = contact["name"]
        key = (to_email.lower(), subject.strip().lower())

        # Guardrail 1 — the address must be verified, never invented.
        ok, source = self.verify_address(to_email)
        if not EMAIL_RE.fullmatch(to_email) or not ok:
            ui.step("GUARDRAIL", ui.RED, f"✖ BLOCKED {to_email!r}: {source}")
            return (f"BLOCKED: {to_email!r} is not a verified address ({source}). "
                    "Call lookup_contact, or ask the user for the address. Never guess.")

        # Guardrail 3 — no duplicates / no retry after a "no".
        if key in self.sent_this_turn:
            return "ALREADY_SENT: this email was already sent for this instruction. Do not send it again."
        if to_email.lower() in self.declined_this_turn:
            return "DECLINED: the user already declined an email to this recipient. Do not retry."

        ui.step("DRAFT", ui.BLUE, origin)
        ui.step("GUARDRAIL", ui.YELLOW, f"recipient verified ✔ ({source}) — "
                + ("human confirmation required" if config.CONFIRM_BEFORE_SEND else "auto-send mode"))
        sender = f"{config.SENDER_NAME} <{config.GMAIL_ADDRESS or 'not-configured'}>"
        ui.draft_box(sender, f"{to_name} <{to_email}>", subject, body, source)

        # Guardrail 2 — human-in-the-loop confirmation.
        if config.CONFIRM_BEFORE_SEND:
            answer = self.confirm_fn({"to_name": to_name, "to_email": to_email,
                                      "subject": subject, "body": body})
            low = answer.strip().lower()
            if low in ("n", "no", "cancel", "stop", ""):
                self.declined_this_turn.add(to_email.lower())
                self.memory.record_email(to_name, to_email, subject, body, "DECLINED")
                ui.step("GUARDRAIL", ui.RED, "✖ user declined — email NOT sent")
                ui.step("MEMORY", ui.MAGENTA, "draft stored as DECLINED in long-term memory")
                return "NOT_SENT: the user declined. Do not retry; tell the user it was cancelled."
            if low not in ("y", "yes", "send", "ok"):
                ui.step("GUARDRAIL", ui.YELLOW, "user requested changes — returning to the LLM")
                return (f"NOT_SENT: the user wants changes: {answer!r}. "
                        "Revise the draft and call send_email again.")

        try:
            message_id = mailer.send_email(to_name, to_email, subject, body)
        except mailer.MailerError as exc:
            self.memory.record_email(to_name, to_email, subject, body, "FAILED")
            ui.step("SEND", ui.RED, f"✖ {exc}")
            return f"FAILED: {exc}"

        self.sent_this_turn.add(key)
        entry = self.memory.record_email(to_name, to_email, subject, body,
                                         "DRY_RUN" if config.DRY_RUN else "SENT", message_id)
        ui.step("SEND", ui.GREEN, f"✔ {config.SMTP_HOST}:{config.SMTP_PORT} accepted the message"
                if not config.DRY_RUN else "dry run — SMTP skipped")
        ui.detail(f"Message-ID {message_id}")
        ui.step("MEMORY", ui.MAGENTA, f"saved as email #{entry['id']} in {config.MEMORY_FILE.name}")
        return f"SENT: email delivered to {to_name} <{to_email}> (Message-ID {message_id})."
