"""Vote endpoint - authenticated voting on posts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, get_db_session
from api.schemas import VoteRequest, VoteResponse, VoteStats
from storage import PostRepository, User, VoteRepository

router = APIRouter()


@router.post("", response_model=VoteResponse)
async def create_vote(
    vote: VoteRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Vote on a post.

    Requires authentication. Vote values:
    - 1: upvote
    - -1: downvote
    - 0: remove vote
    """
    # Verify post exists
    post_repo = PostRepository(session)
    post = await post_repo.get_by_id(vote.post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    # Create user identifier from user id
    user_identifier = f"user:{user.id}"

    # Upsert vote
    vote_repo = VoteRepository(session)
    await vote_repo.upsert_vote(
        post_id=vote.post_id,
        user_identifier=user_identifier,
        value=vote.value,
    )

    # Get updated stats
    stats = await vote_repo.get_post_vote_stats(vote.post_id)

    return VoteResponse(
        success=True,
        post_id=vote.post_id,
        user_vote=vote.value,
        stats=VoteStats(
            total_votes=stats["total_votes"],
            vote_sum=stats["vote_sum"],
            vote_avg=stats["vote_avg"],
        ),
    )


@router.get("/{post_id}", response_model=VoteStats)
async def get_vote_stats(
    post_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get vote statistics for a post."""
    # Verify post exists
    post_repo = PostRepository(session)
    post = await post_repo.get_by_id(post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found",
        )

    vote_repo = VoteRepository(session)
    stats = await vote_repo.get_post_vote_stats(post_id)

    return VoteStats(
        total_votes=stats["total_votes"],
        vote_sum=stats["vote_sum"],
        vote_avg=stats["vote_avg"],
    )
