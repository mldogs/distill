"""Backfill script to populate period_hash for existing Score records.

Usage:
    python -c "
    import asyncio
    from storage.alembic.versions.backfill_period_hash import backfill_period_hashes
    asyncio.run(backfill_period_hashes())
    "

This script:
1. Finds all Score records with NULL period_hash
2. Computes period_hash from (period_start, period_end, ROLLING mode)
3. Updates records in batches
4. Logs progress and errors
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from storage import Database
from storage.models import Score
from ranker.periods import compute_period_hash, Period, PeriodMode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def backfill_period_hashes(
    batch_size: int = 1000,
    dry_run: bool = False,
) -> dict:
    """
    Backfill period_hash for existing Score records.

    Args:
        batch_size: Number of records to process per batch
        dry_run: If True, don't save changes

    Returns:
        dict with statistics
    """
    db = Database()
    stats = {
        "total": 0,
        "updated": 0,
        "errors": 0,
        "skipped": 0,
    }

    try:
        async with db.session() as session:
            # Find scores without period_hash
            query = select(Score).where(Score.period_hash == None)  # noqa: E711
            result = await session.execute(query)
            scores = result.scalars().all()

            stats["total"] = len(scores)
            logger.info(f"Found {stats['total']} scores to backfill")

            if stats["total"] == 0:
                logger.info("No scores to backfill")
                return stats

            # Process in batches
            for i in range(0, len(scores), batch_size):
                batch = scores[i:i + batch_size]
                logger.info(f"Processing batch {i // batch_size + 1} ({len(batch)} records)")

                for score in batch:
                    try:
                        # Determine period type from duration
                        duration_hours = (score.period_end - score.period_start).total_seconds() / 3600

                        # Map duration to Period enum (with tolerance)
                        if abs(duration_hours - 24) < 1:
                            period = Period.DAILY
                        elif abs(duration_hours - 168) < 1:  # 24 * 7
                            period = Period.WEEKLY
                        elif abs(duration_hours - 720) < 1:  # 24 * 30
                            period = Period.MONTHLY
                        else:
                            logger.warning(
                                f"Score {score.id}: unusual duration {duration_hours:.1f}h, "
                                f"skipping"
                            )
                            stats["skipped"] += 1
                            continue

                        # Compute period_hash (assume ROLLING mode for old scores)
                        period_hash = compute_period_hash(
                            period=period,
                            period_start=score.period_start,
                            period_end=score.period_end,
                            mode=PeriodMode.ROLLING,
                        )

                        # Update record
                        if not dry_run:
                            score.period_hash = period_hash
                            stats["updated"] += 1
                        else:
                            logger.info(
                                f"[DRY RUN] Score {score.id}: would set period_hash={period_hash[:16]}..."
                            )
                            stats["updated"] += 1

                    except Exception as e:
                        logger.error(f"Error processing score {score.id}: {e}")
                        stats["errors"] += 1

                # Commit batch
                if not dry_run:
                    await session.commit()
                    logger.info(f"Committed batch {i // batch_size + 1}")

            logger.info(
                f"Backfill complete: {stats['updated']} updated, "
                f"{stats['errors']} errors, {stats['skipped']} skipped"
            )

            return stats

    finally:
        await db.close()


if __name__ == "__main__":
    # Run with dry_run=True first to check
    import sys

    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("=== DRY RUN MODE ===")

    result = asyncio.run(backfill_period_hashes(dry_run=dry_run))
    print(f"\nResults: {result}")
