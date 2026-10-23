import { Badge } from '@/components/ui/badge'
import type { KeyframeFrameStatus } from '@/types/keyframes'
import { FRAME_STATUS_META } from './keyframeSummary'

export const KeyframeStatusBadge = ({ status }: { status: KeyframeFrameStatus }) => {
  const meta = FRAME_STATUS_META[status]
  return <Badge variant={meta.tone}>{meta.label}</Badge>
}
