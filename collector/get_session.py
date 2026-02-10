#!/usr/bin/env python3
"""Generate StringSession for Telegram authentication.

Run once to get the session string, then save it to .env as TG_SESSION.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Load .env from project root
project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
load_dotenv(env_path)

api_id = int(os.environ.get("TG_API_ID", 0))
api_hash = os.environ.get("TG_API_HASH", "")

if not api_id or not api_hash:
    print(f"Error: Set TG_API_ID and TG_API_HASH in {env_path} first")
    exit(1)

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()

    # Read existing .env content
    existing_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            existing_lines = [
                line for line in f.readlines()
                if not line.startswith("TG_SESSION=")
            ]

    # Write updated .env with session
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)
        if existing_lines and not existing_lines[-1].endswith("\n"):
            f.write("\n")
        f.write(f"TG_SESSION={session_string}\n")

    # Set restrictive permissions (owner read/write only)
    os.chmod(env_path, 0o600)

    print(f"\nSession saved to {env_path} (permissions set to 600)")
    print("Keep this file secure - it contains your authentication credentials.")
