import { Button } from '@/components/Common'

interface ShowMoreProps {
  hasMore: boolean
  remaining: number
  onClick: () => void
}

/** "Show more" footer button — renders nothing when the full list is shown. */
export const ShowMore = ({ hasMore, remaining, onClick }: ShowMoreProps) =>
  hasMore ? (
    <div className="flex justify-center pt-4">
      <Button variant="secondary" onClick={onClick}>
        Show more ({remaining} remaining)
      </Button>
    </div>
  ) : null
