import { useState, useEffect } from 'react'
import { api } from '../../../lib/api'
import type { Message } from '@/store/useChatStore'

export type ConfirmationJobType =
  | 'promo'
  | 'reframe'
  | 'production'
  | 'key_moments'
  | 'thumbnails'
  | 'adapts'
  | 'dubbing'

export interface ConfirmationJobParams {
  gcs_uri?: string
  source_filename?: string
  source_mime_type?: string
  mime_type?: string
  prompt_id?: string
  schema_id?: string
  target_duration?: number
  text_overlay?: boolean
  generate_thumbnail?: boolean
  content_type?: string
  blurred_bg?: boolean
  sports_mode?: boolean
  diagnostic_mode?: boolean
  output_aspect_ratio?: '9:16' | '3:4'
  name?: string
  base_concept?: string
  aspect_ratios?: string[]
  target_languages?: string[]
  language_codes?: string[]
  video_filename?: string
  video_source?: string
  production_id?: string
  model_id?: string
  region?: string
  [key: string]: unknown
}

export interface ConfirmationJobResult {
  id?: string
  turn_id?: string
  status?: string
  name?: string
  display_name?: string
}

export interface ConfirmationData {
  job_type: ConfirmationJobType
  title: string
  params: ConfirmationJobParams
  resolved: Record<string, string>
}

export interface UploadSourceItem {
  id: string
  gcs_uri: string
  filename: string
  display_name?: string
  file_size_bytes: number
  mime_type?: string
  image_signed_url?: string
}

export interface ProductionSourceItem {
  id: string
  name: string
  final_video_url: string
  orientation?: string
}

export interface PromptResourceItem {
  id: string
  name: string
  description?: string
  is_active?: boolean
}

export const ROUTE_MAP: Record<ConfirmationJobType, (id: string) => string> = {
  promo: (id) => `/promos/${id}`,
  reframe: (id) => `/orientations/${id}`,
  production: (id) => `/productions/${id}`,
  key_moments: (id) => `/key-moments/${id}`,
  thumbnails: (id) => `/thumbnails/${id}`,
  adapts: (id) => `/adapts/${id}`,
  dubbing: (id) => `/dubbing/${id}`,
}

export async function executeConfirmationJob(
  jobType: ConfirmationJobType,
  params: ConfirmationJobParams,
): Promise<ConfirmationJobResult> {
  const gcsUri = String(params.gcs_uri || '')
  const promptId = String(params.prompt_id || '')
  if (jobType === 'promo') return api.promo.create({ ...params, gcs_uri: gcsUri })
  if (jobType === 'reframe') return api.reframe.create({ ...params, gcs_uri: gcsUri })
  if (jobType === 'production') return api.projects.create(params)
  if (jobType === 'key_moments') return api.keyMoments.analyze({ ...params, gcs_uri: gcsUri, prompt_id: promptId })
  if (jobType === 'thumbnails') return api.thumbnails.analyze({ ...params, gcs_uri: gcsUri, prompt_id: promptId })
  if (jobType === 'adapts') return api.adapts.create({ ...params, gcs_uri: gcsUri })
  return api.dubbing.create({
    gcs_uri: gcsUri,
    source_filename: params.source_filename,
    language_codes: params.target_languages || params.language_codes || [],
    model_id: params.model_id,
  })
}

export function useDubbingLanguages(): { code: string; label: string }[] {
  const [languages, setLanguages] = useState<{ code: string; label: string }[]>([])
  useEffect(() => {
    api.dubbing
      .listLanguages()
      .then((res) => {
        if (Array.isArray(res)) {
          setLanguages(res as { code: string; label: string }[])
        } else if (res && Array.isArray(res.languages)) {
          setLanguages(res.languages.map((l) => ({ code: l.code, label: l.name })))
        }
      })
      .catch(() => {})
  }, [])
  return languages
}

export function useVideoSources(): {
  uploads: UploadSourceItem[]
  productions: ProductionSourceItem[]
  loading: boolean
} {
  const [uploads, setUploads] = useState<UploadSourceItem[]>([])
  const [productions, setProductions] = useState<ProductionSourceItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.promo.listUploadSources().catch(() => []),
      api.promo.listProductionSources().catch(() => []),
    ]).then(([ups, prods]) => {
      setUploads(ups as UploadSourceItem[])
      setProductions(prods as ProductionSourceItem[])
      setLoading(false)
    })
  }, [])

  return { uploads, productions, loading }
}

export function useImageSources(): { images: UploadSourceItem[]; loading: boolean } {
  const [images, setImages] = useState<UploadSourceItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.adapts
      .listUploadSources()
      .then((imgs) => setImages(imgs as UploadSourceItem[]))
      .catch(() => setImages([]))
      .finally(() => setLoading(false))
  }, [])

  return { images, loading }
}

export function usePromptSources(category: string): {
  prompts: PromptResourceItem[]
  loading: boolean
} {
  const [prompts, setPrompts] = useState<PromptResourceItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.system.listResources('prompt', category).then((res) => {
      setPrompts(res as PromptResourceItem[])
      setLoading(false)
    })
  }, [category])

  return { prompts, loading }
}

export async function shareChatTranscript(subset: Message[]): Promise<string> {
  const payload = {
    messages: subset.map((m) => ({
      role: m.role,
      content: m.content,
      agent: m.agent,
      latency_ms: m.latencyMs,
      timestamp: m.timestamp,
    })),
  }
  const res = await api.chat.shareChat(payload)
  return `${window.location.origin}/share/chat/${res.id}`
}
