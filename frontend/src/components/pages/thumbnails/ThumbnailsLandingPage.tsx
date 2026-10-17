import { Image, Camera } from 'lucide-react'
import { api } from '@/hooks/useApiClient'
import { LandingPageShell } from '@/components/shared/LandingPageShell'
import { RecordCard, VideoSourceBadge } from '@/components/shared/RecordCard'
import type { ThumbnailRecord } from '@/types/project'

export const ThumbnailsLandingPage = () => (
  <LandingPageShell<ThumbnailRecord>
    title="Thumbnails"
    subtitle={(count) => `${count} thumbnail${count !== 1 ? 's' : ''}`}
    icon={Image}
    fetchRecords={() => api.thumbnails.list()}
    archiveRecord={(id) => api.thumbnails.archive(id)}
    createPath="/thumbnails/create"
    detailPath="/thumbnails"
    buttonLabel="Create Thumbnail"
    renderCard={(record, onClick, onArchive, showArchive) => (
      <RecordCard
        key={record.id}
        onClick={onClick}
        title={record.display_name || record.video_filename || 'Untitled video'}
        description={record.video_summary}
        status={record.status}
        statusIcon={record.status === 'completed' ? Image : Camera}
        badges={<VideoSourceBadge source={record.video_source} />}
        footerProps={{
          createdAt: record.createdAt,
          extraMeta: (
            <>
              <span className="text-muted-foreground/50">&middot;</span>
              <span>
                {record.screenshots.length} screenshot
                {record.screenshots.length !== 1 ? 's' : ''}
              </span>
            </>
          ),
          showArchive,
          onArchive,
        }}
      >
        {record.thumbnail_signed_url && (
          <div className="mb-3 rounded-lg overflow-hidden border border-border aspect-video bg-black">
            <img
              src={record.thumbnail_signed_url}
              alt="Generated thumbnail"
              className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-105"
            />
          </div>
        )}
      </RecordCard>
    )}
    emptyTitle="No thumbnails yet"
    emptyDescription="Upload a video or select a production to generate a YouTube-style thumbnail with AI."
  />
)
