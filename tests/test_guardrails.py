"""Guardrail tests — run with:  python -m unittest -v

These run without Ollama or Gmail: the LLM is replaced by a scripted fake that
deliberately misbehaves (hallucinates an address), and SMTP is put in dry-run.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402

config.DRY_RUN = True
config.CONFIRM_BEFORE_SEND = True

from agent import EmailAgent  # noqa: E402
from contacts import ContactStore  # noqa: E402
from memory import Memory  # noqa: E402
from tools import Toolbox  # noqa: E402

CONTACTS = [{"name": "Dr. Kunal Meher", "email": "kunal.meher@atlasuniversity.edu.in",
             "aliases": ["Dr. Meher"], "relation": "instructor"},
            {"name": "Anson Dias", "email": "ansondias18@gmail.com",
             "aliases": ["me"], "relation": "owner"}]


def stores(tmp: Path):
    cpath = tmp / "contacts.json"
    cpath.write_text(json.dumps(CONTACTS))
    return ContactStore(cpath), Memory(tmp / "memory.json")


class FakeLLM:
    """Replays a fixed list of assistant messages instead of calling a model."""

    def __init__(self, analysis, steps):
        self.analysis, self.steps = analysis, list(steps)

    def structured(self, messages, schema):
        return self.analysis

    def chat(self, messages, tools=None):
        return self.steps.pop(0)


def call(tool, **args):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": tool, "arguments": args}}]}


class GuardrailTests(unittest.TestCase):
    def __str__(self):                 # print short test names in -v output
        return self._testMethodName

    def shortDescription(self):
        return None

    def setUp(self):
        quiet = contextlib.redirect_stdout(io.StringIO())  # hide the agent trace
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.tmp = Path(tempfile.mkdtemp())
        self.contacts, self.memory = stores(self.tmp)

    def test_lookup_handles_titles_aliases_and_typos(self):
        self.assertEqual(self.contacts.lookup("Prof. Kunal Meher")[0]["email"],
                         "kunal.meher@atlasuniversity.edu.in")
        self.assertEqual(self.contacts.lookup("me")[0]["name"], "Anson Dias")
        self.assertEqual(self.contacts.lookup("Kunal Mehr")[0]["name"], "Dr. Kunal Meher")
        self.assertEqual(self.contacts.lookup("John"), [])

    def test_hallucinated_address_is_blocked(self):
        box = Toolbox(self.contacts, self.memory, confirm_fn=lambda d: "y")
        result = box.send_email("John", "john@gmail.com", "Meeting", "Hi John")
        self.assertTrue(result.startswith("BLOCKED"))
        self.assertEqual(self.memory.emails, [])

    def test_address_typed_by_user_is_accepted(self):
        self.memory.add_turn("user", "his email is john.doe@example.com")
        box = Toolbox(self.contacts, self.memory, confirm_fn=lambda d: "y")
        self.assertTrue(box.save_contact("John", "john.doe@example.com").startswith("SAVED"))
        self.assertTrue(box.send_email("John", "john.doe@example.com", "Hi", "Hello").startswith("SENT"))

    def test_save_contact_refuses_invented_address(self):
        box = Toolbox(self.contacts, self.memory)
        self.assertTrue(box.save_contact("John", "john@company.com").startswith("REFUSED"))

    def test_declined_email_is_not_sent_or_retried(self):
        box = Toolbox(self.contacts, self.memory, confirm_fn=lambda d: "n")
        first = box.send_email("Dr. Kunal Meher", "kunal.meher@atlasuniversity.edu.in", "S", "B")
        again = box.send_email("Dr. Kunal Meher", "kunal.meher@atlasuniversity.edu.in", "S", "B")
        self.assertTrue(first.startswith("NOT_SENT"))
        self.assertTrue(again.startswith("DECLINED"))
        self.assertEqual([e["status"] for e in self.memory.emails], ["DECLINED"])

    def test_duplicate_send_in_one_turn_is_prevented(self):
        box = Toolbox(self.contacts, self.memory, confirm_fn=lambda d: "y")
        box.send_email("Anson Dias", "ansondias18@gmail.com", "S", "B")
        self.assertTrue(box.send_email("Anson Dias", "ansondias18@gmail.com", "S", "B")
                        .startswith("ALREADY_SENT"))

    def test_resend_reuses_memory_and_adapts_greeting(self):
        self.memory.record_email("Dr. Kunal Meher", "kunal.meher@atlasuniversity.edu.in",
                                 "Exp 9", "Dear Dr. Meher,\n\nThe agent works.", "SENT")
        drafts = []
        box = Toolbox(self.contacts, self.memory, confirm_fn=lambda d: drafts.append(d) or "y")
        self.assertTrue(box.resend_email(1, "Anson Dias", "ansondias18@gmail.com").startswith("SENT"))
        self.assertEqual(drafts[0]["subject"], "Exp 9")
        self.assertEqual(drafts[0]["body"], "Dear Anson,\n\nThe agent works.")
        self.assertTrue(box.resend_email(1, "Eve", "eve@evil.com").startswith("BLOCKED"))

    def test_memory_persists_across_restarts(self):
        self.memory.add_turn("user", "hello")
        self.memory.record_email("Anson Dias", "ansondias18@gmail.com", "S", "B", "SENT")
        reloaded = Memory(self.tmp / "memory.json")
        self.assertEqual(reloaded.recent_emails(1)[0]["subject"], "S")
        self.assertEqual(reloaded.user_texts(), ["hello"])

    def test_agent_loop_recovers_after_blocked_hallucination(self):
        """A misbehaving LLM guesses an address; the guardrail blocks it and the
        agent ends up asking the user instead of sending."""
        llm = FakeLLM({"intent": "send_email", "recipients": ["John"], "subject": "Meeting",
                       "key_points": "10 AM", "tone": "friendly",
                       "refers_to_previous_email": False},
                      [call("send_email", to_name="John", to_email="john@gmail.com",
                            subject="Meeting", body="Hi John"),
                       call("lookup_contact", name="John"),
                       {"role": "assistant", "content": "What is John's email address?"}])
        confirmations = []
        agent = EmailAgent(confirm_fn=lambda d: confirmations.append(d) or "y",
                           llm=llm, contacts=self.contacts, memory=self.memory)
        reply = agent.handle("Email John about tomorrow's 10 AM meeting")
        self.assertIn("email address", reply)
        self.assertEqual(confirmations, [])      # never even reached the confirm step
        self.assertEqual(self.memory.emails, [])  # nothing sent


if __name__ == "__main__":
    unittest.main(verbosity=2)
