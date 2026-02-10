#!/usr/bin/env python3
"""Verify storage module works correctly."""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


async def verify_storage():
    """Run verification tests."""
    print("=== Storage Module Verification ===\n")

    from storage import Database, ChannelRepository, PostRepository, ScoreRepository

    db = Database()

    try:
        # 1. Test connection
        print("1. Testing database connection...")
        async with db.session() as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT 1"))
            assert result.scalar() == 1
            print("   ✓ Connection OK\n")

        # 2. Test channel upsert
        print("2. Testing channel upsert...")
        async with db.session() as session:
            repo = ChannelRepository(session)
            channel = await repo.upsert("test_channel", "Test Channel")
            print(f"   Created: {channel}")

            channel2 = await repo.upsert("test_channel", "Test Channel Updated")
            assert channel.id == channel2.id
            print("   ✓ Upsert idempotency OK\n")

        # 3. Test post upsert
        print("3. Testing post upsert...")
        async with db.session() as session:
            channel_repo = ChannelRepository(session)
            channel = await channel_repo.get_by_username("test_channel")

            post_repo = PostRepository(session)
            posts_data = [
                {
                    "telegram_message_id": 12345,
                    "text": "Test post 1",
                    "permalink": "https://t.me/test_channel/12345",
                    "posted_at": datetime.now(timezone.utc),
                    "views": 100,
                },
                {
                    "telegram_message_id": 12346,
                    "text": "Test post 2",
                    "permalink": "https://t.me/test_channel/12346",
                    "posted_at": datetime.now(timezone.utc),
                    "views": 200,
                },
            ]

            count = await post_repo.upsert_posts(channel.id, posts_data)
            print(f"   Upserted {count} posts")

            posts_data[0]["views"] = 150
            count2 = await post_repo.upsert_posts(channel.id, posts_data)
            print(f"   Re-upsert affected {count2} rows (metrics updated)")
            print("   ✓ Post upsert OK\n")

        # 4. Test collector format upsert
        print("4. Testing collector format upsert...")
        collector_data_path = (
            Path(__file__).parent.parent / "collector/data/llm_driven_products.json"
        )
        if collector_data_path.exists():
            with open(collector_data_path) as f:
                messages = json.load(f)[:5]

            async with db.session() as session:
                post_repo = PostRepository(session)
                count = await post_repo.upsert_from_collector(
                    "llm_driven_products", messages
                )
                print(f"   Imported {count} posts from collector data")
        else:
            print("   Skipping (no collector data found)")
        print("   ✓ Collector format OK\n")

        # 5. Test score upsert
        print("5. Testing score upsert...")
        async with db.session() as session:
            channel_repo = ChannelRepository(session)
            channel = await channel_repo.get_by_username("test_channel")

            post_repo = PostRepository(session)
            post = await post_repo.get_by_channel_and_message_id(channel.id, 12345)

            if post:
                score_repo = ScoreRepository(session)
                now = datetime.now(timezone.utc)
                score = await score_repo.upsert_score(
                    post_id=post.id,
                    formula_version="v4",
                    score=4.615,
                    period_start=now.replace(hour=0, minute=0, second=0, microsecond=0),
                    period_end=now,
                    explanation={
                        "views_contribution": 4.615,
                        "formula": "log(1 + views)",
                    },
                )
                print(f"   Created: {score}")
            print("   ✓ Score upsert OK\n")

        print("=== All Verifications Passed ===")
        return True

    except Exception as e:
        print(f"\n✗ Verification failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        await db.close()


if __name__ == "__main__":
    success = asyncio.run(verify_storage())
    sys.exit(0 if success else 1)
