import { Link } from 'react-router-dom'
import { ClipboardList, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface Props {
  recordId: string
  hasPlan: boolean
}

export const ReframePipelineLinks = ({ recordId, hasPlan }: Props) => {
  if (!hasPlan) return null
  return (
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="xs">
        <Link to={`/orientations/${recordId}/plan`} target="_blank">
          <ClipboardList size={14} /> Plan &amp; Quality <ExternalLink size={12} />
        </Link>
      </Button>
    </div>
  )
}
