#!/usr/bin/env python3
"""One-off LOCAL helper to generate a Telethon StringSession.

Run this script interactively on your own machine (NOT in CI / GitHub
Actions) to log in to your Telegram USER account. It prints a StringSession
string at the end - paste that into the TELEGRAM_SESSION GitHub Actions
secret. This script is not part of the scheduled monitor run.

The session string is equivalent to a password for your Telegram account:
never commit it, never share it, never paste it anywhere other than the
GitHub secret field.
"""

from telethon.sessions import StringSession
from telethon.sync import TelegramClient


def main():
    api_id = input("API ID (from https://my.telegram.org): ").strip()
    api_hash = input("API hash (from https://my.telegram.org): ").strip()

    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        client.start()  # interactive: prompts for phone number, login code, 2FA password
        session_str = client.session.save()

    print("\nLogin successful. Your StringSession (treat this like a password):\n")
    print(session_str)
    print("\nPaste the string above into the TELEGRAM_SESSION GitHub Actions secret.")
    print("Do not commit it or share it anywhere else.")


if __name__ == "__main__":
    main()
