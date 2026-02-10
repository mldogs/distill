"""Search endpoint — hybrid lexical + semantic search."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from api.dependencies import get_db_session
from api.schemas import (
    PostResponse,
    SearchResponse,
    SearchResultItem,
    post_to_response,
)
from storage.embedding_client import EmbeddingClient, EmbeddingError
from storage.models import Post, Score
from storage.search import HybridSearchService, SearchFilters

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    mode: str = Query("hybrid", description="Search mode: lexical, semantic, hybrid"),
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    channel: Optional[str] = Query(None, description="Filter by channel username"),
    min_views: Optional[int] = Query(None, ge=0, description="Minimum views"),
    min_replies: Optional[int] = Query(None, ge=0, description="Minimum replies"),
    min_reactions: Optional[int] = Query(None, ge=0, description="Minimum reactions"),
    min_forwards: Optional[int] = Query(None, ge=0, description="Minimum forwards"),
    since: Optional[datetime] = Query(None, description="Posts after this datetime"),
    until: Optional[datetime] = Query(None, description="Posts before this datetime"),
    session: AsyncSession = Depends(get_db_session),
):
    """Search posts using lexical (BM25) or semantic search."""
    if mode not in ("lexical", "semantic", "hybrid"):
        raise HTTPException(status_code=400, detail="mode must be lexical, semantic, or hybrid")

    start = time.perf_counter()

    filters = SearchFilters(
        channel=channel,
        min_views=min_views,
        min_replies=min_replies,
        min_reactions=min_reactions,
        min_forwards=min_forwards,
        since=since,
        until=until,
    )

    # Create embedding client only if semantic mode is requested
    embedding_client: EmbeddingClient | None = None
    if mode in ("semantic", "hybrid"):
        try:
            embedding_client = EmbeddingClient()
        except ValueError:
            # No API key — fall back to lexical
            if mode == "semantic":
                raise HTTPException(
                    status_code=503,
                    detail="Semantic search unavailable: OPENROUTER_API_KEY not configured",
                )
            embedding_client = None

    try:
        service = HybridSearchService(session, embedding_client)
        result = await service.search(
            query=q,
            mode=mode,
            limit=limit,
            offset=offset,
            filters=filters,
        )
    except EmbeddingError as e:
        logger.error(f"Embedding error during search: {e}")
        raise HTTPException(status_code=502, detail="Embedding service error")
    finally:
        if embedding_client is not None:
            await embedding_client.close()

    took_ms = int((time.perf_counter() - start) * 1000)

    # Fetch latest ranking scores for result posts
    post_ids = [hit.post.id for hit in result.hits]
    scores_by_id: dict[int, tuple[float, dict | None]] = {}
    if post_ids:
        score_rows = (
            await session.execute(
                select(Score.post_id, Score.score, Score.explanation)
                .where(Score.post_id.in_(post_ids), Score.formula_version == "v4")
                .order_by(Score.computed_at.desc())
            )
        ).all()
        for row in score_rows:
            if row.post_id not in scores_by_id:
                scores_by_id[row.post_id] = (float(row.score), row.explanation)

    return SearchResponse(
        results=[
            SearchResultItem(
                post=post_to_response(
                    hit.post,
                    score=scores_by_id.get(hit.post.id, (0.0, None))[0],
                    explanation=scores_by_id.get(hit.post.id, (0.0, None))[1],
                ),
                relevance_score=hit.relevance_score,
                match_type=hit.match_type,
            )
            for hit in result.hits
        ],
        total=result.total,
        query=result.query,
        mode=result.mode,
        took_ms=took_ms,
    )
