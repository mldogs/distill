"""Task profiling utilities for Celery tasks."""

from __future__ import annotations

import asyncio
import logging
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


def run_async(coro):
    """Run async coroutine in sync context."""
    return asyncio.run(coro)


async def _create_task_run(task_name: str, input_params: dict | None) -> int | None:
    """Create a task run record in database."""
    try:
        # IMPORTANT: Celery tasks use per-call event loops; do not reuse a global engine
        # across loops (it can cause "Future attached to a different loop" errors).
        from storage import Database, TaskRunRepository

        db = Database()
        try:
            async with db.session() as session:
                repo = TaskRunRepository(session)
                task_run = await repo.create(task_name, input_params)
                await session.commit()
                return task_run.id
        finally:
            await db.close()
    except Exception as e:
        logger.warning(f"Failed to create task run record: {e}")
        return None


async def _finish_task_run(
    task_run_id: int,
    status: str,
    result_summary: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Mark task run as finished."""
    try:
        from storage import Database, TaskRunRepository

        db = Database()
        try:
            async with db.session() as session:
                repo = TaskRunRepository(session)
                await repo.finish(task_run_id, status, result_summary, error_message)
                await session.commit()
        finally:
            await db.close()
    except Exception as e:
        logger.warning(f"Failed to finish task run record: {e}")


def _extract_summary(result: Any) -> dict | None:
    """Extract summary from task result."""
    if result is None:
        return None
    if isinstance(result, dict):
        # Filter out large values
        summary = {}
        for key, value in result.items():
            if isinstance(value, (str, int, float, bool, type(None))):
                summary[key] = value
            elif isinstance(value, list):
                summary[key] = len(value)  # Just store length for lists
            elif isinstance(value, dict):
                summary[key] = f"<dict:{len(value)} keys>"
        return summary
    return {"result": str(result)[:100]}


def profile_task(func: Callable) -> Callable:
    """
    Decorator to profile Celery task execution.

    Records task start, finish time, duration, status, and result summary.

    Usage:
        @celery_app.task(bind=True)
        @profile_task
        def my_task(self, arg1, arg2):
            return {"status": "ok", "count": 42}

    Note: This decorator should be applied AFTER @celery_app.task
    to ensure proper task binding.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        task_name = func.__name__

        # Filter out 'self' from input params for Celery bound tasks
        input_params = {
            k: v for k, v in kwargs.items()
            if not k.startswith("_") and isinstance(v, (str, int, float, bool, list, dict, type(None)))
        }
        # Add positional args (skip self)
        if args:
            # Check if first arg is a Celery task (has 'request' attribute)
            start_idx = 1 if hasattr(args[0], 'request') else 0
            for i, arg in enumerate(args[start_idx:], start=start_idx):
                if isinstance(arg, (str, int, float, bool, list, dict, type(None))):
                    input_params[f"arg{i}"] = arg

        # Create task run record
        task_run_id = run_async(_create_task_run(task_name, input_params))

        try:
            # Execute the actual task
            result = func(*args, **kwargs)

            # Extract result summary
            summary = _extract_summary(result)

            # Mark as success
            if task_run_id:
                run_async(_finish_task_run(task_run_id, "success", summary))

            return result

        except Exception as e:
            # Celery retry exceptions are part of normal control flow; don't label them as "failed".
            try:
                from celery.exceptions import Retry  # type: ignore
            except Exception:
                Retry = None  # type: ignore

            if task_run_id and Retry is not None and isinstance(e, Retry):
                run_async(_finish_task_run(
                    task_run_id,
                    "retry",
                    error_message=str(e)[:500],
                ))
                raise

            # Mark as failed
            if task_run_id:
                run_async(_finish_task_run(
                    task_run_id,
                    "failed",
                    error_message=str(e)[:500],
                ))
            raise

    return wrapper


async def get_profiling_stats(days: int = 7, task_name: str | None = None) -> dict:
    """
    Get aggregated profiling statistics.

    Args:
        days: Number of days to analyze
        task_name: Optional filter by task name

    Returns:
        Dictionary with stats by task and totals
    """
    from storage import get_database, TaskRunRepository

    db = get_database()
    async with db.session() as session:
        repo = TaskRunRepository(session)
        return await repo.get_stats(task_name=task_name, days=days)


async def get_recent_runs(
    limit: int = 50,
    task_name: str | None = None,
) -> list[dict]:
    """
    Get recent task runs.

    Args:
        limit: Maximum number of runs to return
        task_name: Optional filter by task name

    Returns:
        List of task run dictionaries
    """
    from storage import get_database, TaskRunRepository

    db = get_database()
    async with db.session() as session:
        repo = TaskRunRepository(session)
        runs = await repo.get_recent(limit=limit, task_name=task_name)

        return [
            {
                "id": run.id,
                "task_name": run.task_name,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "duration_ms": run.duration_ms,
                "status": run.status,
                "input_params": run.input_params,
                "result_summary": run.result_summary,
                "error_message": run.error_message,
            }
            for run in runs
        ]


async def cleanup_old_runs(days: int = 30) -> int:
    """
    Delete old task runs.

    Args:
        days: Delete runs older than this many days

    Returns:
        Number of deleted records
    """
    from storage import get_database, TaskRunRepository

    db = get_database()
    async with db.session() as session:
        repo = TaskRunRepository(session)
        count = await repo.cleanup_old(days=days)
        await session.commit()
        return count
