import { useAuthStore } from '@/store/useAuthStore'

const API_BASE_URL = '/api/v1'

export interface Project {
  id: string
  name: string
  prompt: string
  refined_prompt?: string
  director_style?: string
  camera_movement?: string
  mood?: string
  location?: string
  character_appearance?: string
  video_length: string
  status: 'draft' | 'generating' | 'completed' | 'failed'
  media_files: any[]
  storyboard_frames: any[]
  created_at: string
  updated_at: string
}

function getInviteCode(): string {
  return useAuthStore.getState().inviteCode || ''
}

function handleAuthError(res: Response) {
  if (res.status === 403) {
    useAuthStore.getState().logout()
  }
}

async function authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const code = getInviteCode()
  const headers = new Headers(init?.headers)
  if (code) {
    headers.set('X-Invite-Code', code)
  }
  const res = await fetch(input, { ...init, headers })
  handleAuthError(res)
  if (res.status === 429) {
    const retryAfter = res.headers.get('Retry-After')
    const seconds = retryAfter ? parseInt(retryAfter, 10) : 60
    throw new Error(`Rate limit exceeded. Please wait ${seconds} seconds.`)
  }
  return res
}

export const api = {
  auth: {
    validate: async (code: string): Promise<{ valid: boolean; is_master: boolean }> => {
      const res = await fetch(`${API_BASE_URL}/auth/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      })
      if (res.status === 429) throw new Error('Too many attempts. Please wait a minute.')
      if (!res.ok) throw new Error(`Validation failed: ${res.status}`)
      return res.json()
    },
    listCodes: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/auth/codes`)
      if (!res.ok) throw new Error(`Failed to list codes: ${res.status}`)
      return res.json()
    },
    createCode: async (data: { code: string; label?: string; daily_credits?: number; expires_at?: string }): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/auth/codes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Failed to create code: ${res.status}`)
      }
      return res.json()
    },
    revokeCode: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/auth/codes/${id}/revoke`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to revoke code: ${res.status}`)
    },
    activateCode: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/auth/codes/${id}/activate`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to activate code: ${res.status}`)
    },
    deleteCode: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/auth/codes/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Failed to delete code: ${res.status}`)
    },
    updateCode: async (id: string, data: { daily_credits?: number; expires_at?: string | null }): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/auth/codes/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Failed to update code: ${res.status}`)
    },
  },
  projects: {
    list: async (params?: { archived?: boolean; mine?: boolean }): Promise<any[]> => {
      const qs = new URLSearchParams()
      if (params?.archived) qs.append('archived', 'true')
      if (params?.mine) qs.append('mine', 'true')
      const query = qs.toString() ? `?${qs.toString()}` : ''
      const res = await authFetch(`${API_BASE_URL}/productions${query}`)
      if (!res.ok) throw new Error(`Failed to list productions: ${res.status}`)
      return res.json()
    },
    get: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/productions/${id}`)
      if (!res.ok) throw new Error(`Failed to get production: ${res.status}`)
      return res.json()
    },
    create: async (project: any): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/productions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(project),
      })
      if (!res.ok) throw new Error(`Failed to create production: ${res.status}`)
      return res.json()
    },
    updateScene: async (id: string, sceneId: string, updates: Record<string, any>): Promise<void> => {
      await authFetch(`${API_BASE_URL}/productions/${id}/scenes/${sceneId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
    },
    analyze: async (id: string, prompt_id?: string, schema_id?: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/productions/${id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_id, schema_id }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Analysis failed: ${res.status}`)
      }
      return res.json()
    },
    buildPrompt: async (id: string, sceneId: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/productions/${id}/scenes/${sceneId}/build-prompt`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error(`Build prompt failed: ${res.status}`)
      return res.json()
    },
    generateFrame: async (id: string, sceneId: string, promptData?: any): Promise<any> => {
      const opts: RequestInit = { method: 'POST' }
      if (promptData) {
        opts.headers = { 'Content-Type': 'application/json' }
        opts.body = JSON.stringify({ prompt_data: promptData })
      }
      const res = await authFetch(`${API_BASE_URL}/productions/${id}/scenes/${sceneId}/frame`, opts)
      if (!res.ok) throw new Error(`Frame generation failed: ${res.status}`)
      return res.json()
    },
    generateSceneVideo: async (id: string, sceneId: string, promptData?: any): Promise<any> => {
      const opts: RequestInit = { method: 'POST' }
      if (promptData) {
        opts.headers = { 'Content-Type': 'application/json' }
        opts.body = JSON.stringify({ prompt_data: promptData })
      }
      const res = await authFetch(`${API_BASE_URL}/productions/${id}/scenes/${sceneId}/video`, opts)
      if (!res.ok) throw new Error(`Video generation failed: ${res.status}`)
      return res.json()
    },
    checkOperation: async (operationName: string, productionId?: string, sceneId?: string): Promise<any> => {
      const params = new URLSearchParams()
      if (productionId) params.append('production_id', productionId)
      if (sceneId) params.append('scene_id', sceneId)
      const qs = params.toString() ? `?${params.toString()}` : ''
      const res = await authFetch(`${API_BASE_URL}/diagnostics/operations/${operationName}${qs}`)
      if (!res.ok) throw new Error(`Operation check failed: ${res.status}`)
      return res.json()
    },
    render: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/productions/${id}/render`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error(`Render failed: ${res.status}`)
      return res.json()
    },
    stitch: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/productions/${id}/stitch`, {
        method: 'POST',
      })
      if (!res.ok) throw new Error(`Stitch failed: ${res.status}`)
      return res.json()
    },
    checkStitchStatus: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/productions/${id}/stitch-status`)
      if (!res.ok) throw new Error(`Stitch status check failed: ${res.status}`)
      return res.json()
    },
    delete: async (id: string): Promise<void> => {
      await authFetch(`${API_BASE_URL}/productions/${id}`, {
        method: 'DELETE',
      })
    },
    archive: async (id: string): Promise<void> => {
      await authFetch(`${API_BASE_URL}/productions/${id}/archive`, {
        method: 'POST',
      })
    },
    unarchive: async (id: string): Promise<void> => {
      await authFetch(`${API_BASE_URL}/productions/${id}/unarchive`, {
        method: 'POST',
      })
    }
  },
  ai: {
    optimizePrompt: async (data: {
      raw_prompt: string
      director_style?: string
      mood?: string
      location?: string
      camera_movement?: string
    }): Promise<{ refined_prompt: string }> => {
      const res = await authFetch(`${API_BASE_URL}/ai/optimize-prompt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    },
    generateStoryboard: async (data: {
      project_id: string
      refined_prompt: string
    }): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/ai/generate-storyboard`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    },
    generateVideo: async (data: {
      project_id: string
      refined_prompt: string
      video_length: string
    }): Promise<{ job_id: string; status: string }> => {
      const res = await authFetch(`${API_BASE_URL}/ai/generate-video`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    }
  },
  keyMoments: {
    list: async (params?: { mine?: boolean }): Promise<any[]> => {
      const query = params?.mine ? '?mine=true' : ''
      const res = await authFetch(`${API_BASE_URL}/key-moments${query}`)
      if (!res.ok) throw new Error(`Failed to list key moments: ${res.status}`)
      return res.json()
    },
    get: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/key-moments/${id}`)
      if (!res.ok) throw new Error(`Failed to get key moments analysis: ${res.status}`)
      return res.json()
    },
    analyze: async (data: { gcs_uri: string; mime_type?: string; prompt_id: string; schema_id?: string; video_filename?: string; video_source?: string; production_id?: string }): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/key-moments/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Key moments analysis failed: ${res.status}`)
      return res.json()
    },
    delete: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/key-moments/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Failed to delete key moments analysis: ${res.status}`)
    },
    update: async (id: string, data: { display_name?: string }): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/key-moments/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Failed to update key moments: ${res.status}`)
    },
    archive: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/key-moments/${id}/archive`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to archive key moments analysis: ${res.status}`)
    },
    listProductionSources: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/key-moments/sources/productions`)
      if (!res.ok) throw new Error(`Failed to list production sources: ${res.status}`)
      return res.json()
    },
  },
  thumbnails: {
    list: async (params?: { mine?: boolean }): Promise<any[]> => {
      const query = params?.mine ? '?mine=true' : ''
      const res = await authFetch(`${API_BASE_URL}/thumbnails${query}`)
      if (!res.ok) throw new Error(`Failed to list thumbnails: ${res.status}`)
      return res.json()
    },
    get: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/${id}`)
      if (!res.ok) throw new Error(`Failed to get thumbnail record: ${res.status}`)
      return res.json()
    },
    analyze: async (data: { gcs_uri: string; mime_type?: string; prompt_id: string; video_filename?: string; video_source?: string; production_id?: string }): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Thumbnail analysis failed: ${res.status}`)
      return res.json()
    },
    saveScreenshots: async (id: string, screenshots: { index: number; gcs_uri: string }[]): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/${id}/screenshots`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ screenshots }),
      })
      if (!res.ok) throw new Error(`Failed to save screenshots: ${res.status}`)
      return res.json()
    },
    generateCollage: async (id: string, prompt_id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/${id}/collage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_id }),
      })
      if (!res.ok) throw new Error(`Collage generation failed: ${res.status}`)
      return res.json()
    },
    update: async (id: string, data: { display_name?: string }): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Failed to update thumbnail: ${res.status}`)
    },
    archive: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/${id}/archive`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to archive thumbnail: ${res.status}`)
    },
    delete: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Failed to delete thumbnail: ${res.status}`)
    },
    listProductionSources: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/thumbnails/sources/productions`)
      if (!res.ok) throw new Error(`Failed to list production sources: ${res.status}`)
      return res.json()
    },
  },
  assets: {
    upload: async (file: File): Promise<{ id: string; gcs_uri: string; signed_url: string; file_type: string }> => {
      const formData = new FormData()
      formData.append('file', file)
      const res = await authFetch(`${API_BASE_URL}/assets/upload`, {
        method: 'POST',
        body: formData,
      })
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
      return res.json()
    },
    initUpload: async (file: File): Promise<{ record_id: string; upload_url: string; gcs_uri: string; content_type: string; expires_at: string }> => {
      const res = await authFetch(`${API_BASE_URL}/assets/upload/init`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || 'application/octet-stream',
          file_size_bytes: file.size,
        }),
      })
      if (!res.ok) throw new Error(`Upload init failed: ${res.status}`)
      return res.json()
    },
    completeUpload: async (recordId: string): Promise<{ id: string; gcs_uri: string; signed_url: string; file_type: string }> => {
      const res = await authFetch(`${API_BASE_URL}/assets/upload/complete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: recordId }),
      })
      if (!res.ok) throw new Error(`Upload complete failed: ${res.status}`)
      return res.json()
    },
    directUpload: (
      file: File,
      onProgress?: (pct: number) => void,
    ): { promise: Promise<{ id: string; gcs_uri: string; signed_url: string; file_type: string }>; abort: () => void } => {
      let xhr: XMLHttpRequest | null = null
      const promise = (async () => {
        const init = await api.assets.initUpload(file)
        onProgress?.(5)

        await new Promise<void>((resolve, reject) => {
          xhr = new XMLHttpRequest()
          xhr.open('PUT', init.upload_url)
          xhr.setRequestHeader('Content-Type', init.content_type)
          // Do NOT send X-Invite-Code to GCS — it triggers CORS preflight failure

          xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
              // Map XHR progress to 5-90% range (init=0-5%, complete=90-100%)
              const pct = Math.round(5 + (e.loaded / e.total) * 85)
              onProgress?.(pct)
            }
          }

          xhr.onload = () => {
            if (xhr!.status >= 200 && xhr!.status < 300) {
              resolve()
            } else {
              reject(new Error(`GCS upload failed: ${xhr!.status}`))
            }
          }
          xhr.onerror = () => reject(new Error('Network error during upload'))
          xhr.onabort = () => reject(new Error('Upload aborted'))

          xhr.send(file)
        })

        onProgress?.(92)
        const result = await api.assets.completeUpload(init.record_id)
        onProgress?.(100)
        return result
      })()

      return {
        promise,
        abort: () => xhr?.abort(),
      }
    },
  },
  uploads: {
    list: async (params?: { file_type?: string; archived?: boolean }): Promise<any[]> => {
      const qs = new URLSearchParams()
      if (params?.file_type) qs.append('file_type', params.file_type)
      if (params?.archived) qs.append('archived', 'true')
      const query = qs.toString() ? `?${qs.toString()}` : ''
      const res = await authFetch(`${API_BASE_URL}/uploads${query}`)
      if (!res.ok) throw new Error(`Failed to list uploads: ${res.status}`)
      return res.json()
    },
    get: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/uploads/${id}`)
      if (!res.ok) throw new Error(`Failed to get upload: ${res.status}`)
      return res.json()
    },
    compress: async (id: string, resolution: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/uploads/${id}/compress`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resolution }),
      })
      if (!res.ok) throw new Error(`Compression failed: ${res.status}`)
      return res.json()
    },
    compressStatus: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/uploads/${id}/compress-status`)
      if (!res.ok) throw new Error(`Compress status check failed: ${res.status}`)
      return res.json()
    },
    update: async (id: string, data: { display_name?: string }): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/uploads/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Failed to update upload: ${res.status}`)
    },
    archive: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/uploads/${id}/archive`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to archive upload: ${res.status}`)
    },
    delete: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/uploads/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Failed to delete upload: ${res.status}`)
    },
  },
  system: {
    getResource: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/system/resources/${id}`)
      if (!res.ok) throw new Error(`Failed to get resource: ${res.status}`)
      return res.json()
    },
    listResources: async (type?: string, category?: string): Promise<any[]> => {
      const params = new URLSearchParams()
      if (type) params.append('type', type)
      if (category) params.append('category', category)
      const res = await authFetch(`${API_BASE_URL}/system/resources?${params.toString()}`)
      return res.json()
    },
    createResource: async (resource: any): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/system/resources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(resource),
      })
      return res.json()
    },
    activateResource: async (id: string): Promise<void> => {
      await authFetch(`${API_BASE_URL}/system/resources/${id}/activate`, {
        method: 'POST',
      })
    },
    getDefaultSchema: async (): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/system/default-schema`)
      return res.json()
    }
  },
  reframe: {
    list: async (params?: { mine?: boolean }): Promise<any[]> => {
      const query = params?.mine ? '?mine=true' : ''
      const res = await authFetch(`${API_BASE_URL}/reframe${query}`)
      if (!res.ok) throw new Error(`Failed to list reframes: ${res.status}`)
      return res.json()
    },
    get: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/reframe/${id}`)
      if (!res.ok) throw new Error(`Failed to get reframe record: ${res.status}`)
      return res.json()
    },
    create: async (data: { gcs_uri: string; source_filename?: string; mime_type?: string; prompt_id?: string; blurred_bg?: boolean; sports_mode?: boolean }): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/reframe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Reframe failed: ${res.status}`)
      return res.json()
    },
    retry: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/reframe/${id}/retry`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to retry reframe: ${res.status}`)
      return res.json()
    },
    update: async (id: string, data: { display_name?: string }): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/reframe/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Failed to update reframe: ${res.status}`)
    },
    archive: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/reframe/${id}/archive`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to archive reframe: ${res.status}`)
    },
    delete: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/reframe/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Failed to delete reframe: ${res.status}`)
    },
    listUploadSources: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/reframe/sources/uploads`)
      if (!res.ok) throw new Error(`Failed to list upload sources: ${res.status}`)
      return res.json()
    },
    listProductionSources: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/reframe/sources/productions`)
      if (!res.ok) throw new Error(`Failed to list production sources: ${res.status}`)
      return res.json()
    },
  },
  promo: {
    list: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/promo`)
      if (!res.ok) throw new Error(`Failed to list promos: ${res.status}`)
      return res.json()
    },
    get: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/promo/${id}`)
      if (!res.ok) throw new Error(`Failed to get promo: ${res.status}`)
      return res.json()
    },
    create: async (data: { gcs_uri: string; source_filename?: string; prompt_id?: string; target_duration?: number; text_overlay?: boolean; generate_thumbnail?: boolean }): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/promo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Promo creation failed: ${res.status}`)
      return res.json()
    },
    retry: async (id: string): Promise<any> => {
      const res = await authFetch(`${API_BASE_URL}/promo/${id}/retry`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to retry promo: ${res.status}`)
      return res.json()
    },
    update: async (id: string, data: { display_name?: string }): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/promo/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (!res.ok) throw new Error(`Failed to update promo: ${res.status}`)
    },
    archive: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/promo/${id}/archive`, { method: 'POST' })
      if (!res.ok) throw new Error(`Failed to archive promo: ${res.status}`)
    },
    delete: async (id: string): Promise<void> => {
      const res = await authFetch(`${API_BASE_URL}/promo/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(`Failed to delete promo: ${res.status}`)
    },
    listUploadSources: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/promo/sources/uploads`)
      if (!res.ok) throw new Error(`Failed to list upload sources: ${res.status}`)
      return res.json()
    },
    listProductionSources: async (): Promise<any[]> => {
      const res = await authFetch(`${API_BASE_URL}/promo/sources/productions`)
      if (!res.ok) throw new Error(`Failed to list production sources: ${res.status}`)
      return res.json()
    },
  },
  diagnostics: {
    optimizePrompt: async (data: any) => {
      const res = await authFetch(`${API_BASE_URL}/diagnostics/optimize-prompt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    },
    generateImage: async (data: any) => {
      const res = await authFetch(`${API_BASE_URL}/diagnostics/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    },
    generateVideo: async (data: any) => {
      const res = await authFetch(`${API_BASE_URL}/diagnostics/generate-video`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    }
  }
}
