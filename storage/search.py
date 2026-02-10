"""Hybrid search service (lexical FTS + semantic embeddings + RRF fusion)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from storage.embedding_client import EmbeddingClient
from storage.models import Channel, Post, PostEmbedding
from storage.text_preprocessor import TextPreprocessor

logger = logging.getLogger(__name__)

# RRF constant (standard value from Cormack et al. 2009)
RRF_K = 60


@dataclass
class SearchFilters:
    """Filters applicable to search results."""

    channel: Optional[str] = None
    min_views: Optional[int] = None
    min_replies: Optional[int] = None
    min_reactions: Optional[int] = None
    min_forwards: Optional[int] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None


@dataclass
class SearchHit:
    """Single search hit with ORM post and relevance info."""

    post: Post
    relevance_score: float
    match_type: str  # "lexical", "semantic", "hybrid"


@dataclass
class SearchResult:
    """Full search result."""

    hits: list[SearchHit] = field(default_factory=list)
    total: int = 0
    query: str = ""
    mode: str = "lexical"


class HybridSearchService:
    """Search service combining BM25 (Postgres FTS) and semantic (pgvector) search."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_client: Optional[EmbeddingClient] = None,
    ):
        self.session = session
        self.embedding_client = embedding_client

    async def search(
        self,
        query: str,
        mode: str = "hybrid",
        limit: int = 20,
        offset: int = 0,
        filters: Optional[SearchFilters] = None,
    ) -> SearchResult:
        """
        Run search in specified mode.

        Modes: "lexical", "semantic", "hybrid".
        Hybrid uses Reciprocal Rank Fusion (RRF) to merge lexical and semantic results.
        Falls back to lexical if embedding client is unavailable.
        """
        if filters is None:
            filters = SearchFilters()

        if mode == "semantic":
            if self.embedding_client is None:
                return SearchResult(query=query, mode=mode)
            return await self._semantic_search(query, limit, offset, filters)

        if mode == "hybrid":
            if self.embedding_client is not None:
                return await self._hybrid_search(query, limit, offset, filters)
            # Fall back to lexical if no embedding client
            return await self._lexical_search(query, limit, offset, filters)

        return await self._lexical_search(query, limit, offset, filters)

    async def _hybrid_search(
        self,
        query: str,
        limit: int,
        offset: int,
        filters: SearchFilters,
    ) -> SearchResult:
        """RRF fusion of lexical and semantic results."""
        # Fetch more candidates from each backend for better fusion
        internal_k = max(limit + offset, 100)

        lexical = await self._lexical_search(query, internal_k, 0, filters)
        semantic = await self._semantic_search(query, internal_k, 0, filters)

        # Build RRF scores: score = w / (k + rank)
        rrf_scores: dict[int, float] = {}  # post_id -> rrf_score
        posts_by_id: dict[int, Post] = {}

        for rank, hit in enumerate(lexical.hits, start=1):
            pid = hit.post.id
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (RRF_K + rank)
            posts_by_id[pid] = hit.post

        for rank, hit in enumerate(semantic.hits, start=1):
            pid = hit.post.id
            rrf_scores[pid] = rrf_scores.get(pid, 0.0) + 1.0 / (RRF_K + rank)
            posts_by_id[pid] = hit.post

        # Sort by RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda pid: rrf_scores[pid], reverse=True)
        total = len(sorted_ids)

        # Apply offset/limit
        page_ids = sorted_ids[offset : offset + limit]

        hits = [
            SearchHit(
                post=posts_by_id[pid],
                relevance_score=rrf_scores[pid],
                match_type="hybrid",
            )
            for pid in page_ids
        ]

        return SearchResult(
            hits=hits,
            total=total,
            query=query,
            mode="hybrid",
        )

    async def _lexical_search(
        self,
        query: str,
        limit: int,
        offset: int,
        filters: SearchFilters,
    ) -> SearchResult:
        """Full-text search using Postgres tsvector + ts_rank."""
        clean_query = TextPreprocessor.clean_for_fts(query)
        if not clean_query:
            return SearchResult(query=query, mode="lexical")

        tsquery = func.plainto_tsquery("russian", clean_query)

        conditions = [Post.search_vector.op("@@")(tsquery)]
        conditions.extend(self._build_filter_conditions(filters))

        # Count
        count_stmt = (
            select(func.count())
            .select_from(Post)
            .where(*conditions)
        )
        total = (await self.session.scalar(count_stmt)) or 0

        # Ranked results
        rank = func.ts_rank(Post.search_vector, tsquery).label("rank")
        stmt = (
            select(Post, rank)
            .options(selectinload(Post.channel))
            .where(*conditions)
            .order_by(rank.desc(), Post.posted_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()

        hits = [
            SearchHit(
                post=row[0],
                relevance_score=float(row[1]),
                match_type="lexical",
            )
            for row in rows
        ]

        return SearchResult(
            hits=hits,
            total=total,
            query=query,
            mode="lexical",
        )

    async def _semantic_search(
        self,
        query: str,
        limit: int,
        offset: int,
        filters: SearchFilters,
    ) -> SearchResult:
        """Semantic search using pgvector cosine distance."""
        clean_query = TextPreprocessor.clean_for_embedding(query)
        if not clean_query or self.embedding_client is None:
            return SearchResult(query=query, mode="semantic")

        query_vec = await self.embedding_client.embed_text(clean_query)

        distance = PostEmbedding.embedding.cosine_distance(query_vec).label("distance")
        similarity = (1 - distance).label("similarity")

        conditions = self._build_filter_conditions(filters)

        # Count
        count_base = (
            select(func.count())
            .select_from(Post)
            .join(PostEmbedding, PostEmbedding.post_id == Post.id)
        )
        if conditions:
            count_base = count_base.where(*conditions)
        total = (await self.session.scalar(count_base)) or 0

        # Ranked results
        stmt = (
            select(Post, similarity)
            .join(PostEmbedding, PostEmbedding.post_id == Post.id)
            .options(selectinload(Post.channel))
            .order_by(distance.asc())
            .offset(offset)
            .limit(limit)
        )
        if conditions:
            stmt = stmt.where(*conditions)

        rows = (await self.session.execute(stmt)).all()

        hits = [
            SearchHit(
                post=row[0],
                relevance_score=float(row[1]),
                match_type="semantic",
            )
            for row in rows
        ]

        return SearchResult(
            hits=hits,
            total=total,
            query=query,
            mode="semantic",
        )

    def _build_filter_conditions(self, filters: SearchFilters) -> list:
        """Build SQLAlchemy filter conditions from SearchFilters."""
        conditions = []
        if filters.channel:
            normalized = filters.channel.lower().lstrip("@")
            conditions.append(
                Post.channel_id.in_(
                    select(Channel.id).where(func.lower(Channel.username) == normalized)
                )
            )
        if filters.min_views is not None:
            conditions.append(func.coalesce(Post.views, 0) >= filters.min_views)
        if filters.min_replies is not None:
            conditions.append(func.coalesce(Post.replies, 0) >= filters.min_replies)
        if filters.min_reactions is not None:
            conditions.append(
                func.coalesce(Post.reactions_count, 0) >= filters.min_reactions
            )
        if filters.min_forwards is not None:
            conditions.append(func.coalesce(Post.forwards, 0) >= filters.min_forwards)
        if filters.since is not None:
            conditions.append(Post.posted_at >= filters.since)
        if filters.until is not None:
            conditions.append(Post.posted_at <= filters.until)
        return conditions
