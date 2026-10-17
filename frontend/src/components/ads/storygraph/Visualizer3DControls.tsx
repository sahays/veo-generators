import { Orbit, ZoomIn, ZoomOut, RotateCcw, CheckCircle2, RefreshCw } from 'lucide-react'
import { Button } from '@/components/Common'
import { KIND_META, type GraphNodeKind, type GraphNode3D } from './graphBuilder3D'

const FILTER_OPTIONS: ReadonlyArray<{ id: GraphNodeKind | 'all'; label: string }> = [
  { id: 'all', label: 'All Layers' },
  { id: 'character', label: 'Characters' },
  { id: 'location', label: 'Locations' },
  { id: 'object', label: 'Objects' },
  { id: 'appearance', label: 'Design Sheets' },
  { id: 'scene', label: 'Scenes' },
  { id: 'shot', label: 'Shots' },
]

export const Visualizer3DToolbar = ({
  nodeCount,
  edgeCount,
  kindFilter,
  onKindFilterChange,
  autoRotate,
  onToggleAutoRotate,
  onZoomIn,
  onZoomOut,
  onReset,
}: {
  nodeCount: number
  edgeCount: number
  kindFilter: GraphNodeKind | 'all'
  onKindFilterChange: (k: GraphNodeKind | 'all') => void
  autoRotate: boolean
  onToggleAutoRotate: () => void
  onZoomIn: () => void
  onZoomOut: () => void
  onReset: () => void
}) => (
  <div className="px-4 py-3 border-b border-border/60 flex flex-wrap items-center justify-between gap-3 bg-card/60">
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex items-center gap-1.5 mr-2">
        <Orbit size={16} className="text-accent-dark" />
        <span className="text-xs font-bold uppercase tracking-wider text-foreground">
          Interactive 3D StoryGraph Constellation
        </span>
        <span className="px-2 py-0.5 rounded bg-accent/10 text-accent-dark text-[10px] font-mono">
          {nodeCount} Nodes · {edgeCount} Edges
        </span>
      </div>

      {FILTER_OPTIONS.map((f) => (
        <Button
          key={f.id}
          size="xs"
          variant={kindFilter === f.id ? 'primary' : 'ghost'}
          onClick={() => onKindFilterChange(f.id)}
        >
          {f.label}
        </Button>
      ))}
    </div>

    <div className="flex items-center gap-1.5">
      <Button
        size="xs"
        variant={autoRotate ? 'primary' : 'outline'}
        icon={Orbit}
        onClick={onToggleAutoRotate}
      >
        {autoRotate ? 'Orbiting' : 'Paused'}
      </Button>
      <Button size="xs" variant="outline" icon={ZoomIn} onClick={onZoomIn}>
        Zoom In
      </Button>
      <Button size="xs" variant="outline" icon={ZoomOut} onClick={onZoomOut}>
        Zoom Out
      </Button>
      <Button size="xs" variant="ghost" icon={RotateCcw} onClick={onReset}>
        Reset
      </Button>
    </div>
  </div>
)

export const Visualizer3DLegend = () => (
  <div className="absolute bottom-3 left-3 flex flex-wrap items-center gap-2 px-3 py-2 rounded-lg bg-black/75 border border-white/10 backdrop-blur-md text-[10px] font-mono text-slate-200 pointer-events-none">
    {(Object.entries(KIND_META) as Array<[GraphNodeKind, (typeof KIND_META)['style']]>).map(
      ([k, meta]) => (
        <span key={k} className="inline-flex items-center gap-1.5">
          <span
            className="w-2.5 h-2.5 rounded-full inline-block"
            style={{ backgroundColor: meta.color }}
          />
          <span>{meta.label}</span>
        </span>
      ),
    )}
    <span className="text-slate-400 ml-2">Drag to rotate 3D · Click any node to inspect</span>
  </div>
)

export const Visualizer3DInspector = ({
  selectedNode,
  canWrite,
  onClose,
  onApproveAppearance,
  onRegenerateAppearance,
}: {
  selectedNode: GraphNode3D
  canWrite: boolean
  onClose: () => void
  onApproveAppearance?: (appearanceId: string) => void
  onRegenerateAppearance?: (appearanceId: string) => void
}) => (
  <div className="lg:col-span-4 border-t lg:border-t-0 lg:border-l border-border/60 bg-card/90 p-4 flex flex-col justify-between space-y-4 max-h-[480px] overflow-y-auto">
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <span
            className="inline-block px-2 py-0.5 rounded text-[9px] font-mono font-bold uppercase text-white mb-1"
            style={{ backgroundColor: selectedNode.color }}
          >
            {KIND_META[selectedNode.kind].label}
          </span>
          <h4 className="text-sm font-bold text-foreground">{selectedNode.label}</h4>
          <p className="text-[11px] font-mono text-muted-foreground">
            ID: {selectedNode.id} · {selectedNode.sublabel}
          </p>
        </div>
        <Button size="xs" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>

      {selectedNode.imageUrl && (
        <div className="rounded-lg overflow-hidden border border-border/60 bg-black aspect-video">
          <img
            src={selectedNode.imageUrl}
            alt={selectedNode.label}
            className="w-full h-full object-cover"
          />
        </div>
      )}

      {selectedNode.videoUrl && (
        <div className="rounded-lg overflow-hidden border border-border/60 bg-black aspect-video">
          <video
            key={selectedNode.videoUrl}
            src={selectedNode.videoUrl}
            controls
            preload="metadata"
            className="w-full h-full"
          />
        </div>
      )}

      {selectedNode.details && Object.keys(selectedNode.details).length > 0 && (
        <div className="space-y-1.5 pt-1">
          {Object.entries(selectedNode.details).map(
            ([k, v]) =>
              v && (
                <div
                  key={k}
                  className="p-2 rounded bg-muted/40 border border-border/50 text-xs"
                >
                  <span className="text-[10px] font-mono uppercase text-muted-foreground block">
                    {k}
                  </span>
                  <span className="text-foreground break-words">{v}</span>
                </div>
              ),
          )}
        </div>
      )}
    </div>

    {canWrite && selectedNode.appearanceId && (
      <div className="pt-3 border-t border-border/50 flex items-center gap-2">
        {selectedNode.status !== 'approved' && onApproveAppearance && (
          <Button
            size="xs"
            variant="primary"
            icon={CheckCircle2}
            onClick={() => onApproveAppearance(selectedNode.appearanceId!)}
          >
            Approve Sheet
          </Button>
        )}
        {onRegenerateAppearance && (
          <Button
            size="xs"
            variant="outline"
            icon={RefreshCw}
            onClick={() => onRegenerateAppearance(selectedNode.appearanceId!)}
          >
            Regenerate Sheet
          </Button>
        )}
      </div>
    )}
  </div>
)
