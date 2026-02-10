#!/usr/bin/env python3
"""
Cleanup test artifacts from the database.

This is intended to remove rows accidentally written by integration tests into a shared DB/schema.
By default it performs a dry-run.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


async def _run(prefix: str, yes: bool) -> int:
    from sqlalchemy import delete, select
    from storage import Database
    from storage.models import Channel

    db = Database()
    try:
        async with db.session() as session:
            stmt = select(Channel).where(Channel.username.like(f"{prefix}%"))
            channels = (await session.execute(stmt)).scalars().all()

            if not channels:
                print(f"No channels found with prefix '{prefix}'")
                return 0

            print(f"Found {len(channels)} channel(s) with prefix '{prefix}':")
            for c in channels[:50]:
                print(f" - @{c.username} (id={c.id})")
            if len(channels) > 50:
                print(f" ... and {len(channels) - 50} more")

            if not yes:
                print("Dry-run: nothing was deleted. Re-run with --yes to delete.")
                return 0

            result = await session.execute(delete(Channel).where(Channel.username.like(f"{prefix}%")))
            # ON DELETE CASCADE should remove dependent posts/scores.
            await session.commit()
            print(f"Deleted {result.rowcount or 0} channel(s) (cascade should remove dependent rows).")
            return 0
    finally:
        await db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prefix",
        default="integration_test_pipeline_",
        help="Channel username prefix to delete (default: integration_test_pipeline_)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete rows (otherwise dry-run)",
    )
    args = parser.parse_args()

    return asyncio.run(_run(prefix=args.prefix, yes=args.yes))


if __name__ == "__main__":
    raise SystemExit(main())
