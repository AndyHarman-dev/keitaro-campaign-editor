interface Props {
  reason: string
  onRetry: () => void
}

/** Shown above the flows instead of numbers; nothing is retried automatically. */
export default function StatsBanner({ reason, onRetry }: Props) {
  return (
    <div role="status" className="alert stats-banner">
      <span><span className="strong">Stats unavailable.</span> {reason[0].toUpperCase() + reason.slice(1)}. Editing and pushing still work.</span>
      <button type="button" className="secondary" onClick={onRetry}>Try again</button>
    </div>
  )
}
