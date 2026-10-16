"""Store the Gmail address + 16-character App Password in a private .env file.

Create the App Password first (2-Step Verification must be on):
    https://myaccount.google.com/apppasswords  ->  name it "Email Agent"  ->  Create

Then run:  python setup_credentials.py
The password is typed hidden, checked against Gmail's SMTP server, and saved to
.env with owner-only permissions. It is never printed.
"""
from __future__ import annotations

import getpass
import os
import re
import smtplib
import ssl
from pathlib import Path

ENV = Path(__file__).resolve().parent / ".env"
DEFAULT = "ansondias18@gmail.com"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def ask_address() -> str:
    while True:
        answer = input(f"Step 1/2 - Gmail ADDRESS (just press Enter for {DEFAULT}): ").strip()
        if not answer:
            return DEFAULT
        if EMAIL_RE.fullmatch(answer):
            return answer
        if len(answer.replace(" ", "")) == 16 and answer.replace(" ", "").isalpha():
            print("  That looks like the App Password - don't paste it here. Press Enter now,\n"
                  "  and paste the password at Step 2 (it will be hidden).")
        else:
            print("  Please enter an email address like name@gmail.com, or press Enter.")


def main() -> None:
    address = ask_address()
    password = getpass.getpass("Step 2/2 - paste the 16-letter App Password (hidden, then Enter): ")
    password = "".join(password.split())
    if len(password) != 16 or not password.isalpha():
        raise SystemExit(f"Expected 16 letters but got {len(password)} characters. "
                         "Copy the App Password again and re-run this script.")

    print(f"Checking the login for {address} with smtp.gmail.com ...")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=30) as s:
            s.login(address, password)
    except smtplib.SMTPAuthenticationError:
        raise SystemExit("Gmail rejected the login: check that the App Password was created "
                         f"for {address}, then re-run this script.")
    except (smtplib.SMTPException, OSError) as exc:
        raise SystemExit(f"Could not log in to Gmail ({exc.__class__.__name__}: {exc}). "
                         "Check the address and your internet connection, then re-run.")

    existing = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()
    existing.update({"GMAIL_ADDRESS": address, "GMAIL_APP_PASSWORD": password})
    existing.setdefault("SENDER_NAME", "Anson Dias")
    ENV.write_text("".join(f"{k}={v}\n" for k, v in existing.items()))
    os.chmod(ENV, 0o600)
    print(f"Login OK. Saved to {ENV} (permissions 600).")


if __name__ == "__main__":
    main()
