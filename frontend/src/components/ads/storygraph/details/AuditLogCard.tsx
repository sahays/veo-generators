import { useState } from 'react'
import { Eye, History, Loader2 } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import type { StoryGraphAuditEntry } from '@/types/project'
import { useAdsProjectActions } from '../../projects/useAdsProjectActions'

const PAGE_SIZE = 50

const AuditRow = ({ ae }: { ae: StoryGraphAuditEntry }) => (
  <div className="p-2.5 rounded bg-muted/30 border border-border/40 text-[11px] flex items-center justify-between gap-2">
    <div>
      <span className="px-1.5 py-0.5 rounded bg-accent/10 text-accent-dark font-mono font-bold mr-2">{ae.role}</span>
      <span className="font-mono text-foreground">{ae.tool}</span>
      <span className="text-muted-foreground ml-2">→ {ae.target_id} (v{ae.after_version})</span>
    </div>
  </div>
)

function useAuditPages(productionId: string) {
  const { projects } = useAdsProjectActions()
  const [entries, setEntries] = useState<StoryGraphAuditEntry[] | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadMore = async () => {
    setLoading(true)
    setError(null)
    try {
      const page = await projects.getAuditLog(productionId, entries ? cursor : null, PAGE_SIZE)
      setEntries((prev) => [...(prev || []), ...page.entries])
      setCursor(page.next_cursor)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit log')
    } finally {
      setLoading(false)
    }
  }
  return { entries, hasMore: entries === null || cursor !== null, loading, error, loadMore }
}

/** Recent audit tail from the snapshot, with on-demand paging through the full history. */
export const AuditLogCard = ({ productionId, recent }: { productionId: string; recent: StoryGraphAuditEntry[] }) => {
  const pages = useAuditPages(productionId)
  const shown = pages.entries ?? recent
  const title = pages.entries ? `Role-Agent Mutation Audit Log (${shown.length} Loaded)` : `Role-Agent Mutation Audit Log (Latest ${recent.length})`
  return (
    <Card title={title} icon={Eye}>
      <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
        {shown.map((ae) => <AuditRow key={ae.id} ae={ae} />)}
      </div>
      {pages.error && <p className="mt-2 text-[11px] text-red-400">{pages.error}</p>}
      {pages.hasMore && (
        <Button size="xs" variant="outline" className="mt-3" icon={pages.loading ? Loader2 : History} disabled={pages.loading} onClick={() => void pages.loadMore()}>
          {pages.entries ? 'Load older entries' : 'Load full history'}
        </Button>
      )}
    </Card>
  )
}
