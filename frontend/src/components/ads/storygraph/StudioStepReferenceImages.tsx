import { CheckCircle2, RefreshCw, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import type {
  StoryGraphAppearance,
  StoryGraphEntity,
} from '@/types/project'
import type { DesignFilter, SelectedInspectorItem } from './storyGraphStudioTypes'

export const StepVisualReferenceSheetsSection = ({
  appearancesCount,
  filteredAppearances,
  entityMap,
  designFilter,
  onDesignFilterChange,
  canWrite,
  busyAction,
  isRunningPipeline,
  onRunStage,
  onAppearanceAction,
  selectedItem,
  onSelectItem,
}: {
  appearancesCount: number
  filteredAppearances: StoryGraphAppearance[]
  entityMap: Record<string, StoryGraphEntity>
  designFilter: DesignFilter
  onDesignFilterChange: (f: DesignFilter) => void
  canWrite: boolean
  busyAction: string | null
  isRunningPipeline: boolean
  onRunStage: (stageId: string) => void
  onAppearanceAction: (appearanceId: string, action: 'approve' | 'regenerate') => void
  selectedItem: SelectedInspectorItem | null
  onSelectItem: (item: SelectedInspectorItem) => void
}) => (
  <div className="space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <p className="text-xs text-muted-foreground mt-0.5">
          Click any reference sheet card to inspect high-res artwork, CRITIC VLM QA telemetry, and Approve/Regenerate controls in the details drawer.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            { id: 'all', label: `All (${appearancesCount})` },
            { id: 'character', label: 'Characters' },
            { id: 'location', label: 'Locations' },
            { id: 'object', label: 'Objects / Props' },
          ] as const
        ).map((f) => (
          <Button key={f.id} size="xs" variant={designFilter === f.id ? 'primary' : 'outline'} onClick={() => onDesignFilterChange(f.id)}>
            {f.label}
          </Button>
        ))}
        {canWrite && (
          <Button size="xs" variant="outline" icon={busyAction === 'S3_DESIGN' ? Loader2 : RefreshCw} onClick={() => onRunStage('S3_DESIGN')} disabled={!!busyAction || isRunningPipeline}>
            Regenerate All Sheets (S3)
          </Button>
        )}
      </div>
    </div>

    <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-5">
      {filteredAppearances.map((appNode: StoryGraphAppearance) => {
        const ent = entityMap[appNode.entity_id]
        const asset = appNode.assets?.[appNode.assets.length - 1]
        const isSelected = selectedItem?.kind === 'appearance' && selectedItem?.id === appNode.id
        return (
          <div
            key={appNode.id}
            onClick={() => onSelectItem({ kind: 'appearance', id: appNode.id, data: { appearance: appNode, entity: ent, asset } })}
            className={cn(
              'cursor-pointer rounded-2xl overflow-hidden border transition-all flex flex-col justify-between',
              isSelected ? 'ring-2 ring-accent bg-accent/10 border-accent shadow-lg' : 'bg-card/80 border-border/70 hover:border-accent/50',
            )}
          >
            <div>
              <div className="aspect-video bg-muted relative overflow-hidden">
                {asset?.signed_url ? (
                  <img src={asset.signed_url} alt={appNode.id} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground">
                    No reference image generated yet
                  </div>
                )}
                <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5">
                  <span className="px-2 py-0.5 rounded bg-black/75 text-white text-[10px] font-mono uppercase">
                    {ent?.entity_type || 'entity'} · v{appNode.version}
                  </span>
                  <span className="px-2 py-0.5 rounded bg-black/75 text-amber-300 text-[10px] font-mono">
                    {appNode.state_label}
                  </span>
                </div>
                <div className="absolute top-2.5 right-2.5">
                  <span className={cn('px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase', appNode.status === 'approved' ? 'bg-emerald-500/90 text-white' : 'bg-amber-500/90 text-black')}>
                    {appNode.status}
                  </span>
                </div>
              </div>
              <div className="p-5 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-1">
                  <h5 className="text-sm font-bold text-foreground">{ent?.canonical_name || appNode.entity_id}</h5>
                  <span className="text-[10px] font-mono text-muted-foreground">{appNode.id}</span>
                </div>
                <p className="text-xs text-muted-foreground line-clamp-3 leading-relaxed">{appNode.visual_description}</p>
              </div>
            </div>
            {canWrite && (
              <div className="px-5 pb-4 pt-2.5 border-t border-border/40 flex items-center justify-between gap-2" onClick={(e) => e.stopPropagation()}>
                <span className="text-[10px] font-mono text-muted-foreground">Click card for VLM QA</span>
                <div className="flex items-center gap-1.5">
                  {appNode.status !== 'approved' && (
                    <Button size="xs" variant="primary" icon={CheckCircle2} onClick={() => onAppearanceAction(appNode.id, 'approve')} disabled={!!busyAction}>
                      Approve
                    </Button>
                  )}
                  <Button size="xs" variant="outline" icon={RefreshCw} onClick={() => onAppearanceAction(appNode.id, 'regenerate')} disabled={!!busyAction}>
                    Regen
                  </Button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  </div>
)
