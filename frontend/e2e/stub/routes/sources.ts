/**
 * `GET {base}/sources/uploads` and `GET {base}/sources/productions`: the video
 * pickers of every media feature use the same two lists (see `UploadItem` and
 * `ProductionItem` in `src/components/shared/VideoSourceSelector.tsx`).
 */
import { PRODUCTIONS, videoUploads } from '../data/catalog.ts'
import { VIDEO_FILE } from '../media.ts'
import { ok, route, type Route, type RouteContext } from '../lib/router.ts'

function uploadSources(ctx: RouteContext) {
  const url = ctx.mediaUrl(VIDEO_FILE)
  return videoUploads().map((u) => ({
    id: u.id,
    filename: u.filename,
    display_name: u.display_name ?? '',
    gcs_uri: u.gcs_uri,
    video_signed_url: url,
    file_size_bytes: u.file_size_bytes,
    createdAt: u.createdAt,
  }))
}

function productionSources(ctx: RouteContext) {
  const url = ctx.mediaUrl(VIDEO_FILE)
  return PRODUCTIONS.map((p) => ({ ...p, video_signed_url: url }))
}

/** `base` is the feature prefix, e.g. `/api/v1/scene-analysis`. */
export function sourceRoutes(base: string): Route[] {
  return [
    route('GET', `${base}/sources/uploads`, (ctx) => ok(uploadSources(ctx))),
    route('GET', `${base}/sources/productions`, (ctx) => ok(productionSources(ctx))),
  ]
}
