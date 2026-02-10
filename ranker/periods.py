"""Period utilities for ranking time ranges."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum


class PeriodMode(str, Enum):
    """Period boundary calculation mode."""

    ROLLING = "rolling"  # Sliding window from now
    CALENDAR = "calendar"  # Calendar-aligned (week, month start)


class Period(str, Enum):
    """Supported ranking periods."""

    DAILY = "24h"
    WEEKLY = "7d"
    MONTHLY = "30d"
    ALL = "all"

    @property
    def hours(self) -> int:
        """Get period duration in hours."""
        mapping = {
            Period.DAILY: 24,
            Period.WEEKLY: 24 * 7,
            Period.MONTHLY: 24 * 30,
            Period.ALL: 24 * 365 * 10,  # 10 years (practical "all time")
        }
        return mapping[self]

    @property
    def label(self) -> str:
        """Human-readable label."""
        mapping = {
            Period.DAILY: "Daily",
            Period.WEEKLY: "Weekly",
            Period.MONTHLY: "Monthly",
            Period.ALL: "All time",
        }
        return mapping[self]


def parse_period(value: str) -> Period:
    """
    Parse period string to Period enum.

    Accepts: "24h", "7d", "30d", "daily", "weekly", "monthly"
    """
    value = value.lower().strip()

    aliases = {
        "daily": Period.DAILY,
        "weekly": Period.WEEKLY,
        "monthly": Period.MONTHLY,
        "all": Period.ALL,
        "24h": Period.DAILY,
        "7d": Period.WEEKLY,
        "30d": Period.MONTHLY,
    }

    if value in aliases:
        return aliases[value]

    raise ValueError(f"Unknown period: {value}. Valid: {list(aliases.keys())}")


def get_period_bounds(
    period: Period,
    reference: datetime | None = None,
) -> tuple[datetime, datetime]:
    """
    Get start and end datetime for a period.

    Args:
        period: The period type
        reference: Reference time (default: now UTC)

    Returns:
        Tuple of (period_start, period_end)
    """
    if reference is None:
        reference = datetime.now(timezone.utc)

    # Ensure reference has timezone
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    end = reference
    start = end - timedelta(hours=period.hours)

    return start, end


def get_period_bounds_from_dates(
    start_date: datetime,
    end_date: datetime,
) -> tuple[datetime, datetime]:
    """
    Normalize date bounds ensuring timezone awareness.

    Args:
        start_date: Start datetime
        end_date: End datetime

    Returns:
        Tuple of (start, end) with UTC timezone
    """
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)

    return start_date, end_date


def bucket_period_end(
    reference: datetime,
    period: Period,
    mode: PeriodMode = PeriodMode.ROLLING,
) -> datetime:
    """
    Round period_end to stable bucket to prevent Score explosion.

    For ROLLING mode:
    - DAILY: round to nearest hour
    - WEEKLY: round to start of day (midnight UTC)
    - MONTHLY: round to start of day (midnight UTC)

    For CALENDAR mode:
    - DAILY: start of day (midnight)
    - WEEKLY: start of ISO week (Monday 00:00)
    - MONTHLY: start of month (1st 00:00)

    Args:
        reference: Reference time (typically now)
        period: Period type
        mode: Boundary calculation mode

    Returns:
        Bucketed period_end datetime
    """
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    if mode == PeriodMode.CALENDAR:
        if period == Period.DAILY:
            # Start of day
            return reference.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == Period.WEEKLY:
            # Start of ISO week (Monday)
            days_since_monday = reference.weekday()
            week_start = reference - timedelta(days=days_since_monday)
            return week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == Period.MONTHLY:
            # Start of month
            return reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:  # ROLLING mode with bucketing
        if period == Period.DAILY:
            # Round to nearest hour
            return reference.replace(minute=0, second=0, microsecond=0)
        elif period in (Period.WEEKLY, Period.MONTHLY):
            # Round to start of day for longer periods
            return reference.replace(hour=0, minute=0, second=0, microsecond=0)

    return reference


def get_bucketed_period_bounds(
    period: Period,
    reference: datetime | None = None,
    mode: PeriodMode = PeriodMode.ROLLING,
) -> tuple[datetime, datetime]:
    """
    Get stable period boundaries with bucketing to prevent Score explosion.

    This is the recommended function for scheduled ranking tasks.

    Args:
        period: Period type
        reference: Reference time (default: now UTC)
        mode: Boundary calculation mode (default: ROLLING)

    Returns:
        Tuple of (period_start, period_end) with stable boundaries
    """
    if reference is None:
        reference = datetime.now(timezone.utc)

    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    # Get bucketed end
    period_end = bucket_period_end(reference, period, mode)

    # Calculate start based on bucketed end
    if mode == PeriodMode.CALENDAR:
        if period == Period.DAILY:
            period_start = period_end  # Already start of day
        elif period == Period.WEEKLY:
            period_start = period_end  # Already start of week
        elif period == Period.MONTHLY:
            period_start = period_end  # Already start of month
    else:  # ROLLING
        period_start = period_end - timedelta(hours=period.hours)

    return period_start, period_end


def compute_period_hash(
    period: Period,
    period_start: datetime,
    period_end: datetime,
    mode: PeriodMode = PeriodMode.ROLLING,
) -> str:
    """
    Compute deterministic hash for period identification.

    This hash uniquely identifies a period bucket and is used for:
    - Matching stored scores in feed API
    - Enforcing Score uniqueness constraint
    - Preventing duplicate score records

    Args:
        period: Period type
        period_start: Normalized period start (UTC, no microseconds)
        period_end: Normalized period end (UTC, no microseconds)
        mode: Period mode (ROLLING or CALENDAR)

    Returns:
        SHA256 hash (hex string, 64 chars)
    """
    # Normalize to UTC and strip microseconds for consistency
    if period_start.tzinfo is None:
        period_start = period_start.replace(tzinfo=timezone.utc)
    if period_end.tzinfo is None:
        period_end = period_end.replace(tzinfo=timezone.utc)

    period_start = period_start.replace(microsecond=0)
    period_end = period_end.replace(microsecond=0)

    # Build deterministic string
    components = [
        mode.value,
        period.value,
        period_start.isoformat(),
        period_end.isoformat(),
    ]
    hash_input = "|".join(components)

    # Compute SHA256
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
