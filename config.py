"""Central configuration for the Experiment 9 AI Email Agent.

Secrets (Gmail address + 16-character App Password) live in a local `.env`
file that is never committed. Create it with:  python setup_credentials.py
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE per line) so the project has no dependencies."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


_load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# LLM (reasoning / planning) — a local model served by Ollama
# ---------------------------------------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("AGENT_MODEL", "qwen2.5:7b")
TEMPERATURE = 0.0          # deterministic drafts
SEED = 42
MAX_AGENT_STEPS = 8        # max LLM <-> tool round-trips per user instruction

# ---------------------------------------------------------------------------
# Safety / guardrails
# ---------------------------------------------------------------------------
# True  -> every outgoing email is shown to the user and needs an explicit "y".
# False -> the agent sends directly (recipient verification still applies).
CONFIRM_BEFORE_SEND = _flag("CONFIRM_BEFORE_SEND", True)
# True  -> run the whole pipeline but do not open an SMTP connection.
DRY_RUN = _flag("DRY_RUN", False)

# ---------------------------------------------------------------------------
# Email delivery — Gmail SMTP over SSL with an App Password
# ---------------------------------------------------------------------------
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
SENDER_NAME = os.environ.get("SENDER_NAME", "Anson Dias")
SENDER_TITLE = os.environ.get("SENDER_TITLE", "TY-BTech AIML (SEM VI), APP ID 2307040")
# Appended to every email so recipients know an AI agent drafted it.
FOOTER = (
    "\n\n--\nThis email was drafted by an AI email agent "
    "(Experiment 9, LLM and Agentic AI) and sent after the sender confirmed it."
)

# ---------------------------------------------------------------------------
# Memory + contacts stores (plain JSON files)
# ---------------------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
CONTACTS_FILE = Path(os.environ.get("AGENT_CONTACTS_FILE", DATA_DIR / "contacts.json"))
MEMORY_FILE = Path(os.environ.get("AGENT_MEMORY_FILE", DATA_DIR / "memory.json"))
SHORT_TERM_TURNS = 12      # conversation turns replayed to the LLM each request
