import { Link } from 'react-router-dom'
import { ClipboardList, ExternalLink } from 'lucide-react'

interface Props {
  recordId: string
  hasPlan: boolean
}

const linkClass =
  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors'

export const ReframePipelineLinks = ({ recordId, hasPlan }: Props) => {
  if (!hasPlan) return null
  return (
    <div className="flex flex-wrap gap-2">
      <Link to={`/orientations/${recordId}/plan`} target="_blank" className={linkClass}>
        <ClipboardList size={14} /> Plan &amp; Quality <ExternalLink size={12} />
      </Link>
    </div>
  )
}
