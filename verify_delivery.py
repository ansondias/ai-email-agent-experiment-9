"""Confirm, over IMAP, that the emails the agent reported as SENT really exist in Gmail.

For every SENT email in data/memory.json it searches the Gmail "Sent Mail" folder
(and the Inbox, for copies sent to yourself) by Message-ID and prints the
headers Gmail stored. Uses the same App Password as the agent.

    python verify_delivery.py
"""
from __future__ import annotations

import email
import imaplib
import json
from email.header import decode_header, make_header

import config

FOLDERS = ['"[Gmail]/Sent Mail"', "INBOX"]


def header(msg, name: str) -> str:
    return str(make_header(decode_header(msg.get(name, ""))))


def main() -> None:
    sent = [e for e in json.loads(config.MEMORY_FILE.read_text())["emails"] if e["status"] == "SENT"]
    print(f"{len(sent)} email(s) marked SENT in {config.MEMORY_FILE.name}; checking Gmail over IMAP...\n")
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=60)
    imap.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
    for e in sent:
        print(f"#{e['id']} → {e['to_email']}   Message-ID {e['message_id']}")
        for folder in FOLDERS:
            imap.select(folder, readonly=True)
            # Gmail's indexed search (much faster than a raw HEADER scan of the mailbox)
            mid = e["message_id"].strip("<>")
            _, data = imap.search(None, "X-GM-RAW", f'"rfc822msgid:{mid}"')
            ids = data[0].split()
            if not ids:
                print(f"    {folder:<20} not found")
                continue
            _, parts = imap.fetch(ids[0], "(BODY.PEEK[HEADER])")
            msg = email.message_from_bytes(parts[0][1])
            print(f"    {folder:<20} FOUND  Date: {header(msg, 'Date')}")
            print(f"    {'':<20}        From: {header(msg, 'From')}")
            print(f"    {'':<20}        To:   {header(msg, 'To')}")
            print(f"    {'':<20}        Subj: {header(msg, 'Subject')}")
        print()
    imap.logout()


if __name__ == "__main__":
    import functools, builtins
    print = functools.partial(builtins.print, flush=True)  # noqa: A001
    main()
