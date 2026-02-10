from __future__ import annotations
#!/usr/bin/env python3
"""CLI for running post ranking."""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path for imports
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

from sqlalchemy import func, select

from ranker.formulas import available_formulas, get_formula
from ranker.periods import Period, get_period_bounds, parse_period
from ranker.scorer import Scorer
from storage.database import get_session
from storage.models import Channel


def parse_date(date_str: str) -> datetime:
    """Parse date string (YYYY-MM-DD) to datetime."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def format_score_result(result, rank: int, verbose: bool = False) -> str:
    """Format a single score result for display."""
    lines = [f"{rank}. Post #{result.post_id} — Score: {result.score:.4f}"]

    if verbose:
        exp = result.explanation
        inputs = exp.get("inputs", {})
        components = exp.get("components", {})

        lines.append(f"   Views: {inputs.get('views', 0):,}")
        if "forwards" in inputs:
            lines.append(f"   Forwards: {inputs.get('forwards', 0):,}")
        if "reactions" in inputs:
            lines.append(f"   Reactions: {inputs.get('reactions', 0):,}")
        if "replies" in inputs:
            lines.append(f"   Replies: {inputs.get('replies', 0):,}")
        if "age_hours" in inputs:
            lines.append(f"   Age: {inputs.get('age_hours', 0):.1f}h")
        if "freshness_factor" in components:
            lines.append(f"   Freshness: {components['freshness_factor']:.4f}")

    return "\n".join(lines)


async def run_ranking(
    formula_version: str,
    period: Period | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    save: bool = False,
    top_n: int = 10,
    verbose: bool = False,
) -> None:
    """Run ranking and display results."""

    # Determine period bounds
    if since and until:
        period_start, period_end = since, until
        period_label = f"{since.date()} to {until.date()}"
    elif period:
        period_start, period_end = get_period_bounds(period)
        period_label = period.label
    else:
        # Default to daily
        period = Period.DAILY
        period_start, period_end = get_period_bounds(period)
        period_label = period.label

    formula = get_formula(formula_version)

    print(f"Ranking posts with formula {formula.name}")
    print(f"Period: {period_label}")
    print(f"  Start: {period_start.isoformat()}")
    print(f"  End:   {period_end.isoformat()}")
    print()

    async with get_session() as session:
        # For v4: compute dynamic global average posts per day
        global_avg_posts_per_day = None
        if formula_version == "v4":
            avg_query = select(func.avg(Channel.posts_per_day_30d)).where(
                Channel.is_active == True,  # noqa: E712
                Channel.posts_per_day_30d != None,  # noqa: E711
                Channel.posts_per_day_30d > 0,
            )
            result = await session.execute(avg_query)
            global_avg_posts_per_day = result.scalar()
            if global_avg_posts_per_day:
                print(f"Global avg posts/day: {global_avg_posts_per_day:.2f}")

        scorer = Scorer(session, formula, global_avg_posts_per_day=global_avg_posts_per_day)

        if save:
            scores, saved_count = await scorer.rank_and_save(
                period_start, period_end, limit
            )
            print(f"Processed {len(scores)} posts, saved {saved_count} scores")
        else:
            scores = await scorer.rank_period(period_start, period_end, limit)
            print(f"Processed {len(scores)} posts (dry run, not saved)")

        await session.commit()

    print()
    print(f"Top {min(top_n, len(scores))} results:")
    print("-" * 40)

    for i, result in enumerate(scores[:top_n], 1):
        print(format_score_result(result, i, verbose))
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Rank Telegram posts using scoring formulas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m ranker.cli --formula v4 --period 24h
  python -m ranker.cli --formula v4 --since 2026-01-01 --until 2026-01-10
  python -m ranker.cli --formula v4 --period weekly --save --top 20
        """,
    )

    parser.add_argument(
        "--formula",
        "-f",
        default="v4",
        choices=available_formulas(),
        help=f"Scoring formula version (default: v1). Available: {available_formulas()}",
    )

    parser.add_argument(
        "--period",
        "-p",
        help="Period type: 24h/daily, 7d/weekly, 30d/monthly",
    )

    parser.add_argument(
        "--since",
        help="Start date (YYYY-MM-DD). Use with --until for custom range",
    )

    parser.add_argument(
        "--until",
        help="End date (YYYY-MM-DD). Use with --since for custom range",
    )

    parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=1000,
        help="Max posts to process (default: 1000)",
    )

    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="Save scores to database (default: dry run)",
    )

    parser.add_argument(
        "--top",
        "-t",
        type=int,
        default=10,
        help="Number of top results to display (default: 10)",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed score breakdown",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.since and not args.until:
        parser.error("--since requires --until")
    if args.until and not args.since:
        parser.error("--until requires --since")
    if args.since and args.period:
        parser.error("Cannot use --period with --since/--until")

    # Parse dates if provided
    since = parse_date(args.since) if args.since else None
    until = parse_date(args.until) if args.until else None

    # Parse period if provided
    period = parse_period(args.period) if args.period else None

    # Run ranking
    try:
        asyncio.run(
            run_ranking(
                formula_version=args.formula,
                period=period,
                since=since,
                until=until,
                limit=args.limit,
                save=args.save,
                top_n=args.top,
                verbose=args.verbose,
            )
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
