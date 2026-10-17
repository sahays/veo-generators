import { Zap, Clock, Tag, Image as ImageIcon } from 'lucide-react'
import { api } from '@/hooks/useApiClient'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard, VideoSourceBadge } from '@/components/shared/RecordCard'
import type { KeyMomentsRecord } from '@/types/project'

export const KeyMomentsLandingPage = () => (
  <LandingPageShell<KeyMomentsRecord>
    title="Key Moments"
    subtitle={(count) => `${count} analysis${count !== 1 ? 'es' : ''}`}
    icon={Zap}
    fetchRecords={() => api.keyMoments.list()}
    archiveRecord={(id) => api.keyMoments.archive(id)}
    createPath="/key-moments/analyze"
    detailPath="/key-moments"
    buttonLabel="Find Key Moments"
    gridClassName="grid grid-cols-1 gap-4"
    renderCard={(record, onClick, onArchive, showArchive) => {
      const firstMoment = record.key_moments?.[0]

      return (
        <RecordCard
          key={record.id}
          onClick={onClick}
          title={record.display_name || record.video_filename || 'Untitled video'}
          description={record.video_summary}
          badges={<VideoSourceBadge source={record.video_source} />}
          titleRight={
            <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium shrink-0 text-emerald-600 bg-emerald-500/10">
              <Clock size={10} />
              {record.moment_count} moment{record.moment_count !== 1 ? 's' : ''}
            </span>
          }
          footerProps={{
            createdAt: record.createdAt,
            showArchive,
            onArchive,
          }}
        >
          {record.key_moments && record.key_moments.length > 0 && (
            <div className="flex gap-2 mb-3 overflow-hidden">
              {record.key_moments.slice(0, 4).map((moment, i) => (
                <div
                  key={i}
                  className="relative w-20 shrink-0 aspect-video rounded-md overflow-hidden bg-muted border border-border/50"
                >
                  {moment.frame_signed_url ? (
                    <img
                      src={moment.frame_signed_url}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <ImageIcon size={12} className="text-muted-foreground/40" />
                    </div>
                  )}
                </div>
              ))}
              {record.key_moments.length > 4 && (
                <div className="w-10 shrink-0 aspect-video rounded-md bg-accent/10 flex items-center justify-center text-[10px] font-bold text-accent-dark border border-accent/20">
                  +{record.key_moments.length - 4}
                </div>
              )}
            </div>
          )}

          {firstMoment?.tags && firstMoment.tags.length > 0 && (
            <div className="flex items-center gap-1 mb-3 flex-wrap">
              <Tag size={10} className="text-muted-foreground shrink-0" />
              {firstMoment.tags.slice(0, 4).map((tag, j) => (
                <span
                  key={j}
                  className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </RecordCard>
      )
    }}
    emptyTitle="No analyses yet"
    emptyDescription="Upload a video or select a production to discover key moments with AI."
  />
)
