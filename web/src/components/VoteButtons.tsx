"use client";

import { useState } from "react";
import { usePostHog } from "posthog-js/react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";

interface VoteButtonsProps {
  postId: number;
  initialVote?: number;
  initialSum?: number;
}

export function VoteButtons({
  postId,
  initialVote = 0,
  initialSum = 0,
}: VoteButtonsProps) {
  const { isAuthenticated } = useAuth();
  const posthog = usePostHog();
  const [userVote, setUserVote] = useState(initialVote);
  const [voteSum, setVoteSum] = useState(initialSum);
  const [loading, setLoading] = useState(false);

  async function handleVote(value: -1 | 0 | 1) {
    if (loading) return;

    if (!isAuthenticated) {
      return;
    }

    const newValue = userVote === value ? 0 : value;

    // Optimistic update
    const oldVote = userVote;
    const oldSum = voteSum;
    setUserVote(newValue);
    setVoteSum(voteSum - oldVote + newValue);

    setLoading(true);
    try {
      const response = await api.vote({ post_id: postId, value: newValue });
      setUserVote(response.user_vote);
      setVoteSum(response.stats.vote_sum);

      posthog?.capture("vote", {
        post_id: postId,
        vote_value: newValue,
        vote_type: newValue === 1 ? "upvote" : newValue === -1 ? "downvote" : "remove",
      });
    } catch (error) {
      setUserVote(oldVote);
      setVoteSum(oldSum);
      console.error("Vote failed:", error);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col items-center gap-0.5">
      {/* Upvote button */}
      <button
        onClick={() => handleVote(1)}
        disabled={loading || !isAuthenticated}
        className={`
          p-1 text-lg transition-all leading-none
          ${userVote === 1
            ? "text-[var(--success)]"
            : "text-[var(--muted)] hover:text-[var(--success)]"
          }
          ${loading ? "opacity-50" : ""}
          ${!isAuthenticated ? "cursor-not-allowed opacity-40" : ""}
        `}
        title={isAuthenticated ? "Upvote" : "Login to vote"}
      >
        ▲
      </button>

      {/* Vote count */}
      <span
        className={`
          text-xs font-medium
          ${voteSum > 0
            ? "text-[var(--success)]"
            : voteSum < 0
            ? "text-[var(--danger)]"
            : "text-[var(--muted)]"
          }
        `}
      >
        {voteSum > 0 ? `+${voteSum}` : voteSum}
      </span>

      {/* Downvote button */}
      <button
        onClick={() => handleVote(-1)}
        disabled={loading || !isAuthenticated}
        className={`
          p-1 text-lg transition-all leading-none
          ${userVote === -1
            ? "text-[var(--danger)]"
            : "text-[var(--muted)] hover:text-[var(--danger)]"
          }
          ${loading ? "opacity-50" : ""}
          ${!isAuthenticated ? "cursor-not-allowed opacity-40" : ""}
        `}
        title={isAuthenticated ? "Downvote" : "Login to vote"}
      >
        ▼
      </button>
    </div>
  );
}
