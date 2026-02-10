interface ScoreExplainerProps {
  score: number;
}

export function ScoreExplainer({ score }: ScoreExplainerProps) {
  return (
    <span className="font-medium text-[var(--primary)]">
      🔥 {score.toFixed(1)}
    </span>
  );
}
