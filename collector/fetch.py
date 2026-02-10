#!/usr/bin/env python3
"""Telegram channel message collector using Telethon."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.sessions import StringSession

from collector.errors import FetchPermanentError, FetchTransientError

# Load .env from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")


def parse_since_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse since date (YYYY-MM-DD) to inclusive datetime bound (00:00 UTC)."""
    if not date_str:
        return None
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def parse_until_date_exclusive(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse until date (YYYY-MM-DD) into an exclusive upper bound (next day 00:00 UTC).

    This makes `until=YYYY-MM-DD` behave as "include the whole day YYYY-MM-DD".
    """
    if not date_str:
        return None
    return parse_since_date(date_str) + timedelta(days=1)


def get_env_or_fail(name: str) -> str:
    """Get environment variable or raise error."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


def serialize_message(msg, channel_username: str) -> dict:
    """Convert Telethon message to serializable dict."""
    data = {
        "id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "text": msg.text if msg.text is not None else None,
        "permalink": f"https://t.me/{channel_username}/{msg.id}",
    }
    if msg.views is not None:
        data["views"] = msg.views
    if msg.forwards is not None:
        data["forwards"] = msg.forwards
    if hasattr(msg, "replies") and msg.replies is not None:
        data["replies"] = msg.replies.replies if hasattr(msg.replies, "replies") else 0
    if hasattr(msg, "reactions") and msg.reactions is not None:
        # Sum all reaction counts
        total_reactions = 0
        if hasattr(msg.reactions, "results"):
            for reaction in msg.reactions.results:
                total_reactions += getattr(reaction, "count", 0)
        data["reactions_count"] = total_reactions

    # Forward info — для графа связей между каналами
    if msg.fwd_from:
        if hasattr(msg.fwd_from, "from_id") and msg.fwd_from.from_id:
            # Получаем channel_id источника
            from_id = msg.fwd_from.from_id
            if hasattr(from_id, "channel_id"):
                data["forwarded_from_channel_id"] = from_id.channel_id
        if msg.fwd_from.channel_post:
            data["forwarded_from_message_id"] = msg.fwd_from.channel_post

    # Media type — для фильтрации по типу контента
    if msg.media:
        data["media_type"] = type(msg.media).__name__

    # Edit date — для трекинга изменений
    if msg.edit_date:
        data["edited_at"] = msg.edit_date.isoformat()

    # Grouped ID — для альбомов (несколько фото/видео в одном посте)
    grouped_id = getattr(msg, "grouped_id", None)
    if grouped_id:
        data["grouped_id"] = grouped_id

    return data


async def fetch_messages(
    channel: str,
    limit: Optional[int],
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    max_attempts: int = 3,
) -> list:
    """Fetch messages from a Telegram channel."""
    api_id = int(get_env_or_fail("TG_API_ID"))
    api_hash = get_env_or_fail("TG_API_HASH")
    session_str = get_env_or_fail("TG_SESSION")

    for attempt in range(1, max_attempts + 1):
        try:
            async with TelegramClient(StringSession(session_str), api_id, api_hash) as client:
                entity = await client.get_entity(channel)
                channel_username = getattr(entity, "username", None) or channel.lstrip("@")

                messages = []
                async for msg in client.iter_messages(entity, limit=limit, offset_date=until):
                    if msg.date is None:
                        continue
                    if since and msg.date < since:
                        break
                    messages.append(serialize_message(msg, channel_username))

                return messages
        except FloodWaitError as e:
            retry_after = int(getattr(e, "seconds", 0) or 0)
            # Avoid blocking worker concurrency on long waits: let the caller reschedule.
            raise FetchTransientError(
                f"Telegram FloodWait: retry after {retry_after}s",
                retry_after=retry_after or None,
            ) from e
        except ValueError as e:
            # Telethon may surface "username not found" as ValueError rather than UsernameNotOccupiedError.
            msg = str(e)
            if (
                "No user has" in msg
                or "Cannot find any entity corresponding to" in msg
                or "username is not in use" in msg
            ):
                raise FetchPermanentError(msg, reason="username_not_found") from e
            raise
        except UsernameInvalidError as e:
            raise FetchPermanentError(str(e), reason="username_invalid") from e
        except UsernameNotOccupiedError as e:
            raise FetchPermanentError(str(e), reason="username_not_occupied") from e
        except ChannelPrivateError as e:
            raise FetchPermanentError(str(e), reason="channel_private") from e
        except Exception as e:
            if attempt >= max_attempts:
                raise FetchTransientError(f"Fetch failed after {attempt} attempts: {e}") from e
            await asyncio.sleep(min(2 ** (attempt - 1), 10))
            continue


def load_config(path: str) -> dict:
    """Load channels config from YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Fetch messages from Telegram channel")
    parser.add_argument("--channel", help="Channel username (e.g. @channel)")
    parser.add_argument("--limit", type=int, default=100, help="Max messages (ignored if --since/--until set)")
    parser.add_argument("--out", help="Output JSON file path")
    parser.add_argument("--config", help="Path to channels.yaml config file")
    parser.add_argument("--out-dir", default=".", help="Output directory for config mode")
    parser.add_argument("--since", help="Fetch messages after this date (YYYY-MM-DD)")
    parser.add_argument("--until", help="Fetch messages until this date (inclusive, YYYY-MM-DD)")
    args = parser.parse_args()

    since = parse_since_date(args.since)
    until = parse_until_date_exclusive(args.until)

    if args.config:
        config = load_config(args.config)
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        for ch in config["channels"]:
            username = ch["username"]
            name = ch.get("name", username.lstrip("@"))
            name = name.replace("..", "_").replace("/", "_").replace("\\", "_")
            ch_since = parse_since_date(ch.get("since")) or since
            ch_until = parse_until_date_exclusive(ch.get("until")) or until
            # Use limit only if no date filters specified
            limit = None if (ch_since or ch_until) else ch.get("limit", 100)
            out_path = out_dir / f"{name}.json"

            print(f"Fetching {username}...")
            messages = asyncio.run(fetch_messages(username, limit, ch_since, ch_until))

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(messages, f, ensure_ascii=False, indent=2)

            print(f"Saved {len(messages)} messages to {out_path}")
    else:
        if not args.channel or not args.out:
            parser.error("--channel and --out are required when not using --config")

        # Use limit only if no date filters specified
        limit = None if (since or until) else args.limit
        messages = asyncio.run(fetch_messages(args.channel, limit, since, until))

        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)

        print(f"Saved {len(messages)} messages to {args.out}")


if __name__ == "__main__":
    main()
