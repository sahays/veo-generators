import { motion } from 'framer-motion'
import { User, Archive } from 'lucide-react'
import { cn, getTimeAgo } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import type { Avatar } from '@/types/avatar'
import { PRESET_CATALOG, STYLE_LABELS } from '@/types/avatar'

// v2 avatars built from a Gemini Live preset don't have a GCS portrait —
// look up the bundled preset PNG instead.
const PRESET_IMAGE_BY_ID: Record<string, string> = Object.fromEntries(
  PRESET_CATALOG.map((p) => [p.id, p.imageUrl]),
)

function avatarThumbnailUrl(record: Avatar): string | null {
  if (record.image_signed_url) return record.image_signed_url
  if (record.preset_name && PRESET_IMAGE_BY_ID[record.preset_name]) {
    return PRESET_IMAGE_BY_ID[record.preset_name]
  }
  return null
}

const STYLE_STYLES: Record<string, string> = {
  talkative: 'text-amber-600 bg-amber-500/10',
  funny: 'text-pink-600 bg-pink-500/10',
  serious: 'text-slate-600 bg-slate-500/10',
  cynical: 'text-indigo-600 bg-indigo-500/10',
  to_the_point: 'text-emerald-600 bg-emerald-500/10',
}

const AvatarCard = ({
  record,
  onClick,
  onArchive,
  showArchive,
}: {
  record: Avatar
  onClick: () => void
  onArchive: (e: React.MouseEvent) => void
  showArchive: boolean
}) => (
  <motion.button
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    whileHover={{ y: -2 }}
    onClick={onClick}
    className="glass bg-card p-5 rounded-xl text-left transition-all duration-200 hover:border-accent/40 group w-full"
  >
    <div className="aspect-[3/4] rounded-lg overflow-hidden bg-muted mb-3 border border-border/50">
      {(() => {
        const url = avatarThumbnailUrl(record)
        return url ? (
          <img src={url} alt={record.name} className="w-full h-full object-cover" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-muted-foreground">
            <User size={32} />
          </div>
        )
      })()}
    </div>

    <div className="flex items-center gap-2 mb-1.5">
      <h4 className="text-sm font-heading font-bold text-foreground group-hover:text-accent-dark transition-colors line-clamp-1 flex-1">
        {record.name}
      </h4>
      {record.is_default && (
        <span className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/10 text-accent-dark">
          default
        </span>
      )}
    </div>

    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
      <span
        className={cn(
          'px-1.5 py-0.5 rounded-full text-[9px] font-medium',
          STYLE_STYLES[record.style] || STYLE_STYLES.to_the_point,
        )}
      >
        {STYLE_LABELS[record.style] || record.style}
      </span>
      <div className="flex items-center gap-2">
        <span>{getTimeAgo(record.createdAt)}</span>
        {showArchive && !record.is_default && (
          <button
            onClick={onArchive}
            className="p-1 -m-1 rounded hover:bg-muted hover:text-foreground transition-colors opacity-0 group-hover:opacity-100"
            title="Archive"
          >
            <Archive size={12} />
          </button>
        )}
      </div>
    </div>
  </motion.button>
)

export const AvatarLandingPage = () => (
  <LandingPageShell<Avatar>
    title="Avatars"
    subtitle={(n) => `${n} avatar${n === 1 ? '' : 's'} · talk to one to get a lip-synced video reply`}
    icon={User}
    fetchRecords={() => api.avatars.list()}
    archiveRecord={(id) => api.avatars.archive(id)}
    createPath="/avatars/create"
    detailPath="/avatars"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <AvatarCard
        key={record.id}
        record={record}
        onClick={onClick}
        onArchive={onArchive}
        showArchive={showArchive}
      />
    )}
    emptyTitle="No avatars yet"
    emptyDescription="Upload a portrait, give it a name and a style, then ask it anything."
    buttonLabel="New Avatar"
  />
)
