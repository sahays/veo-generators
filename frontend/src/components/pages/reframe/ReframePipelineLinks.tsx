import { Link } from 'react-router-dom'
import { ExternalLink } from 'lucide-react'

interface Props {
  recordId: string
  hasTrackSummary: boolean
  hasPrompt: boolean
  hasGeminiScenes: boolean
  hasFocalPoints: boolean
  hasSpeakerSegments: boolean
  hasSegmentPlan: boolean
  hasEvalReport: boolean
}

const linkClass =
  'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors'

export const ReframePipelineLinks = ({
  recordId,
  hasTrackSummary,
  hasPrompt,
  hasGeminiScenes,
  hasFocalPoints,
  hasSpeakerSegments,
  hasSegmentPlan,
  hasEvalReport,
}: Props) => {
  if (
    !(hasTrackSummary || hasPrompt || hasGeminiScenes || hasFocalPoints || hasSpeakerSegments || hasSegmentPlan || hasEvalReport)
  ) return null
  return (
    <div className="flex flex-wrap gap-2">
      {hasEvalReport && (
        <Link to={`/orientations/${recordId}/eval-report`} target="_blank" className={linkClass}>
          Quality <ExternalLink size={12} />
        </Link>
      )}
      {hasSegmentPlan && (
        <Link to={`/orientations/${recordId}/decisions`} target="_blank" className={linkClass}>
          Decisions <ExternalLink size={12} />
        </Link>
      )}
      {hasTrackSummary && (
        <Link to={`/orientations/${recordId}/mediapipe`} target="_blank" className={linkClass}>
          MediaPipe <ExternalLink size={12} />
        </Link>
      )}
      {hasSpeakerSegments && (
        <Link to={`/orientations/${recordId}/chirp`} target="_blank" className={linkClass}>
          Chirp <ExternalLink size={12} />
        </Link>
      )}
      {hasPrompt && (
        <Link to={`/orientations/${recordId}/prompt`} target="_blank" className={linkClass}>
          Prompt <ExternalLink size={12} />
        </Link>
      )}
      {hasGeminiScenes && (
        <Link to={`/orientations/${recordId}/gemini`} target="_blank" className={linkClass}>
          Gemini <ExternalLink size={12} />
        </Link>
      )}
      {hasFocalPoints && (
        <Link to={`/orientations/${recordId}/focal-points`} target="_blank" className={linkClass}>
          Focal Points <ExternalLink size={12} />
        </Link>
      )}
    </div>
  )
}
