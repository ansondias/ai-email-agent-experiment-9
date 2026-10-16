"""Experiment 9 — AI Email Agent.

    AI Agent = LLM (reasoning/planning) + Memory (context/state)
               + Tools (actions) + Orchestration (this file)

For each natural-language instruction the orchestrator:
  1. UNDERSTAND  — the LLM extracts intent + entities as schema-constrained JSON
  2. PLAN / ACT  — a ReAct-style loop: the LLM chooses tools (lookup_contact,
                   save_contact, recall_recent_emails, send_email, resend_email)
                   and sees their results
  3. DRAFT       — the LLM writes the subject and body
  4. GUARDRAIL   — address verification + human confirmation before sending
  5. SEND        — Gmail SMTP with an App Password
  6. REMEMBER    — conversation + emails persisted for follow-up instructions

Run interactively:  python agent.py
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Dict, List, Optional

import config
import ui
from contacts import ContactStore
from llm import LLMError, OllamaClient
from memory import Memory
from tools import TOOL_SCHEMAS, ConfirmFn, Toolbox

UNDERSTAND_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string",
                   "enum": ["send_email", "resend_previous", "provide_info", "query_history",
                            "cancel", "other"]},
        "recipients": {"type": "array", "items": {"type": "string"}},
        "subject": {"type": "string"},
        "key_points": {"type": "string"},
        "tone": {"type": "string", "enum": ["formal", "friendly", "neutral", "urgent"]},
        "refers_to_previous_email": {"type": "boolean"},
    },
    "required": ["intent", "recipients", "subject", "key_points", "tone",
                 "refers_to_previous_email"],
}

UNDERSTAND_PROMPT = """You analyse instructions given to an email assistant.
Extract the intent and entities of the user's LATEST message. Use earlier turns only to
resolve references such as "the same email", "too", "his address is ...".
- intent: send_email (write a new email) | resend_previous (send an already-written email
  to someone else) | provide_info (answering the assistant's question, e.g. giving an
  address) | query_history (asking about past emails) | cancel | other
- recipients: who to email NOW, as names or addresses exactly as written in the
  conversation (e.g. "Dr. Meher", "me"). For "send the same email to X too" this is only
  X, not the earlier recipient. For provide_info, the person the address belongs to.
  Never invent or complete an email address that the user did not type.
- subject: a short subject line for a new email ("" for resend_previous / provide_info)
- key_points: what the email must say, in a few words
- tone: formal for professors or official matters, otherwise as the user asks
- refers_to_previous_email: true if the message points back to an earlier email"""


def system_prompt(memory: Memory) -> str:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return f"""You are an AI email assistant acting for {config.SENDER_NAME} <{config.GMAIL_ADDRESS}>.
Today is {today:%A, %d %B %Y}. You turn natural-language instructions into emails and
send them with your tools.

Rules:
1. For EVERY recipient call lookup_contact with the name the user used — even if you
   think you know the address. "me"/"myself" means {config.SENDER_NAME}.
2. If lookup_contact returns NOT_FOUND, never invent or guess an address: ask the user
   for it and stop. When the user replies with the address, FIRST call
   save_contact(name, email) so it is remembered, THEN write and send the email that
   was waiting for that address.
3. Write a clear subject and a complete body in the requested tone. Greet the recipient
   by name and write relative dates as real dates (tomorrow = {tomorrow:%A, %d %B %Y}).
   Refer to people by name rather than he/she. The body
   must not repeat the subject line and must have no placeholders like [Your Name].
   End the email body (not your chat replies) with this sign-off:
   Regards,
   {config.SENDER_NAME}
   {config.SENDER_TITLE}
4. Call send_email once per recipient. The user sees the draft and must confirm. If the
   result is NOT_SENT because the user declined, do not retry.
5. If the user means an earlier email ("the same email", "that one too"), call
   recall_recent_emails, then lookup_contact for the new recipient, then resend_email
   with that email_id. Do not rewrite the email.
6. When finished, tell the user what happened in THIS request in one or two plain
   sentences, e.g. "Sent your email to <recipient>." or "Cancelled - nothing was sent."
   Chat replies have no greeting and no signature. Never claim an email was sent unless
   the send tool returned SENT.
7. For questions about past emails, call recall_recent_emails and answer from its result.

Long-term memory: {memory.summary()} Read it with recall_recent_emails."""


def current_task_note(a: Dict) -> str:
    """Pin the LLM to the request parsed in step 1 so it does not redo older tasks."""
    return ("CURRENT TASK (from the understanding step): "
            f"intent={a.get('intent')}, recipients={a.get('recipients')}, "
            f"subject={a.get('subject')!r}, key points={a.get('key_points')!r}, "
            f"tone={a.get('tone')}. Earlier messages are context only; the tasks in them "
            "are already finished. Act only on the current task."
            + (" Call recall_recent_emails(count=5) and answer only from its result."
               if a.get("intent") == "query_history" else ""))


class EmailAgent:
    def __init__(self, confirm_fn: Optional[ConfirmFn] = None,
                 llm: Optional[OllamaClient] = None,
                 contacts: Optional[ContactStore] = None,
                 memory: Optional[Memory] = None):
        self.llm = llm or OllamaClient()
        self.contacts = contacts or ContactStore(config.CONTACTS_FILE)
        self.memory = memory or Memory(config.MEMORY_FILE, config.SHORT_TERM_TURNS)
        self.tools = Toolbox(self.contacts, self.memory, confirm_fn)

    # Step 1 — intent + entity extraction (schema-constrained JSON)
    def understand(self) -> Dict:
        messages = [{"role": "system", "content": UNDERSTAND_PROMPT}] + self.memory.recent_turns()[-6:]
        return self.llm.structured(messages, UNDERSTAND_SCHEMA)

    # Steps 2-6 — the reasoning / tool-use loop
    def handle(self, user_text: str) -> str:
        started, llm_calls, tool_calls = time.perf_counter(), 1, 0
        self.memory.add_turn("user", user_text)
        self.tools.new_turn()

        analysis = self.understand()
        ui.understand(analysis)

        messages: List[Dict] = [{"role": "system", "content": system_prompt(self.memory)}]
        messages += self.memory.recent_turns()
        messages.append({"role": "system", "content": current_task_note(analysis)})

        reply = ""
        for _ in range(config.MAX_AGENT_STEPS):
            msg = self.llm.chat(messages, TOOL_SCHEMAS)
            llm_calls += 1
            calls = msg.get("tool_calls") or []
            if not calls:
                reply = (msg.get("content") or "").strip()
                if reply:
                    break
                # Orchestrator check: the model stalled without acting or answering.
                messages.append({"role": "user", "content":
                                 "Continue the task: call the next tool you need, "
                                 "or reply to me if you are finished."})
                continue
            messages.append({"role": "assistant", "content": msg.get("content", ""),
                             "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = self.tools.run(fn.get("name", ""), args)
                tool_calls += 1
                messages.append({"role": "tool", "tool_name": fn.get("name", ""), "content": result})

        reply = reply or "I stopped because the task needed too many steps. Please rephrase it."
        self.memory.add_turn("assistant", reply)
        ui.agent_reply(reply, f"{time.perf_counter() - started:.1f} s · {llm_calls} LLM calls · "
                              f"{tool_calls} tool calls")
        return reply


def main() -> None:
    ui.banner(config.MODEL, config.CONFIRM_BEFORE_SEND, config.DRY_RUN,
              config.GMAIL_ADDRESS or "(not configured)")
    agent = EmailAgent()
    print(ui.c(ui.DIM, "Type an instruction, e.g. \"Email Dr. Meher that my report is ready\". "
                       "Ctrl-D to quit.\n"))
    while True:
        try:
            text = input(ui.c(ui.BOLD + ";" + ui.BLUE, "You ▸ ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in ("quit", "exit"):
            break
        if text:
            try:
                agent.handle(text)
            except LLMError as exc:
                print(ui.c(ui.RED, str(exc)))


if __name__ == "__main__":
    main()
