import { User } from 'lucide-react'
import { cn } from '@/lib/utils'
import { api } from '@/lib/api'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard } from '@/components/shared/RecordCard'
import type { Avatar } from '@/types/avatar'
import { PRESET_CATALOG, STYLE_LABELS } from '@/types/avatar'

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

export const AvatarLandingPage = () => (
  <LandingPageShell<Avatar>
    title="Avatars"
    subtitle={(n) => `${n} avatar${n === 1 ? '' : 's'} · talk to one to get a lip-synced video reply`}
    icon={User}
    fetchRecords={() => api.avatars.list()}
    archiveRecord={(id) => api.avatars.archive(id)}
    createPath="/avatars/create"
    detailPath="/avatars"
    renderCard={(record, onClick, onArchive, showArchive) => {
      const url = avatarThumbnailUrl(record)
      return (
        <RecordCard
          key={record.id}
          onClick={onClick}
          title={record.name}
          badges={
            record.is_default ? (
              <span className="text-[8px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-accent/10 text-accent-dark">
                default
              </span>
            ) : undefined
          }
          footerProps={{
            createdAt: record.createdAt,
            leftContent: (
              <span
                className={cn(
                  'px-1.5 py-0.5 rounded-full text-[9px] font-medium',
                  STYLE_STYLES[record.style] || STYLE_STYLES.to_the_point,
                )}
              >
                {STYLE_LABELS[record.style] || record.style}
              </span>
            ),
            showArchive: showArchive && !record.is_default,
            onArchive,
          }}
        >
          <div className="aspect-[3/4] rounded-lg overflow-hidden bg-muted mb-3 border border-border/50">
            {url ? (
              <img
                src={url}
                alt={record.name}
                className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                <User size={32} />
              </div>
            )}
          </div>
        </RecordCard>
      )
    }}
    emptyTitle="No avatars yet"
    emptyDescription="Upload a portrait, give it a name and a style, then ask it anything."
    buttonLabel="New Avatar"
  />
)
