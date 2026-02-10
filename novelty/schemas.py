"""Pydantic schemas for novelty scoring with multi-criteria evaluation."""

from pydantic import BaseModel, Field
from typing import Optional


# Single source of truth for criteria: (name, description)
CRITERIA_DEFS: list[tuple[str, str]] = [
    ("exclusivity", "0=widely covered, 0.5=among first, 1=exclusive/breaking"),
    ("uniqueness", "0=common topic, 0.5=known with nuance, 1=rare topic"),
    ("depth", "0=headline/retell, 0.5=basic overview, 1=detailed analysis"),
    ("perspective", "0=conventional view, 0.5=slight twist, 1=unique angle"),
    ("factual", "0=opinions only, 0.5=mixed facts/opinions, 1=concrete facts"),
    ("data", "0=no data, 0.5=some numbers, 1=statistics/research"),
    ("sources", "0=no sources, 0.5=secondary sources, 1=primary sources"),
    ("context", "0=isolated fact, 0.5=partial context, 1=full picture"),
    ("actionable", "0=abstract, 0.5=general advice, 1=specific actions"),
    ("clarity", "0=messy, 0.5=readable, 1=well structured"),
]

NOVELTY_CRITERIA = [name for name, _ in CRITERIA_DEFS]


class CriteriaScores(BaseModel):
    """Individual criterion scores (0, 0.5, or 1)."""

    exclusivity: float = Field(..., ge=0.0, le=1.0)
    uniqueness: float = Field(..., ge=0.0, le=1.0)
    depth: float = Field(..., ge=0.0, le=1.0)
    perspective: float = Field(..., ge=0.0, le=1.0)
    factual: float = Field(..., ge=0.0, le=1.0)
    data: float = Field(..., ge=0.0, le=1.0)
    sources: float = Field(..., ge=0.0, le=1.0)
    context: float = Field(..., ge=0.0, le=1.0)
    actionable: float = Field(..., ge=0.0, le=1.0)
    clarity: float = Field(..., ge=0.0, le=1.0)

    @classmethod
    def neutral(cls) -> "CriteriaScores":
        """All criteria at 0.5 (neutral/unknown)."""
        return cls(**{name: 0.5 for name in NOVELTY_CRITERIA})

    def compute_weighted_score(self, weights: dict[str, float]) -> float:
        """Compute weighted average score."""
        scores = self.model_dump()
        total_weight = 0.0
        weighted_sum = 0.0
        for criterion, score in scores.items():
            weight = weights.get(criterion, 1.0)
            weighted_sum += score * weight
            total_weight += weight
        return weighted_sum / total_weight if total_weight else 0.5


class NoveltyAnalysis(BaseModel):
    """Structured output from LLM novelty analysis."""

    criteria: CriteriaScores
    reasoning: str = Field(..., max_length=500)
    key_insights: list[str] = Field(default_factory=list, max_length=5)
    similar_topics_count: int = Field(default=0, ge=0)

    @property
    def novelty_score(self) -> float:
        """Compute simple average for backward compatibility."""
        return self.criteria.compute_weighted_score({})


class NoveltyResult(BaseModel):
    """Result of novelty analysis for a post."""

    post_id: int
    novelty_score: float = Field(ge=0.0, le=1.0)
    criteria_scores: CriteriaScores
    analysis: Optional[NoveltyAnalysis] = None
    model_used: str
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        result = {
            "post_id": self.post_id,
            "novelty_score": self.novelty_score,
            "criteria": self.criteria_scores.model_dump(),
            "model_used": self.model_used,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
        }
        if self.analysis:
            result["reasoning"] = self.analysis.reasoning
            result["key_insights"] = self.analysis.key_insights
            result["similar_topics_count"] = self.analysis.similar_topics_count
        else:
            result["reasoning"] = "Analysis not available"
            result["key_insights"] = []
            result["similar_topics_count"] = 0
        return result


def _build_analysis_schema() -> dict:
    """Generate JSON schema for OpenRouter structured output from CRITERIA_DEFS."""
    criteria_props = {}
    for name, desc in CRITERIA_DEFS:
        criteria_props[name] = {
            "type": "number",
            "enum": [0, 0.5, 1],
            "description": desc,
        }
    return {
        "type": "object",
        "properties": {
            "criteria": {
                "type": "object",
                "properties": criteria_props,
                "required": NOVELTY_CRITERIA,
                "additionalProperties": False,
            },
            "reasoning": {
                "type": "string",
                "maxLength": 500,
                "description": "Brief explanation of the scores",
            },
            "key_insights": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "List of unique insights found in the post",
            },
            "similar_topics_count": {
                "type": "integer",
                "minimum": 0,
                "description": "Approximate number of similar posts in context",
            },
        },
        "required": ["criteria", "reasoning", "key_insights", "similar_topics_count"],
        "additionalProperties": False,
    }


NOVELTY_ANALYSIS_SCHEMA = _build_analysis_schema()
