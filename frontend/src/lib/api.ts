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

export const api = {
  projects: {
    list: async (): Promise<any[]> => {
      const res = await fetch(`${API_BASE_URL}/productions`)
      return res.json()
    },
    get: async (id: string): Promise<any> => {
      const res = await fetch(`${API_BASE_URL}/productions/${id}`)
      return res.json()
    },
    create: async (project: any): Promise<any> => {
      const res = await fetch(`${API_BASE_URL}/productions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(project),
      })
      return res.json()
    },
    analyze: async (id: string, prompt_id?: string, schema_id?: string): Promise<any> => {
      const res = await fetch(`${API_BASE_URL}/productions/${id}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt_id, schema_id }),
      })
      return res.json()
    },
    render: async (id: string): Promise<void> => {
      await fetch(`${API_BASE_URL}/productions/${id}/render`, {
        method: 'POST',
      })
    },
    delete: async (id: string): Promise<void> => {
      await fetch(`${API_BASE_URL}/productions/${id}`, {
        method: 'DELETE',
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
      const res = await fetch(`${API_BASE_URL}/ai/optimize-prompt`, {
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
      const res = await fetch(`${API_BASE_URL}/ai/generate-storyboard`, {
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
      const res = await fetch(`${API_BASE_URL}/ai/generate-video`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    }
  },
  assets: {
    upload: async (file: File): Promise<{ gcs_uri: string; signed_url: string }> => {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(`${API_BASE_URL}/assets/upload`, {
        method: 'POST',
        body: formData,
      })
      return res.json()
    }
  },
  system: {
    listResources: async (type?: string, category?: string): Promise<any[]> => {
      const params = new URLSearchParams()
      if (type) params.append('type', type)
      if (category) params.append('category', category)
      const res = await fetch(`${API_BASE_URL}/system/resources?${params.toString()}`)
      return res.json()
    },
    createResource: async (resource: any): Promise<any> => {
      const res = await fetch(`${API_BASE_URL}/system/resources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(resource),
      })
      return res.json()
    },
    activateResource: async (id: string): Promise<void> => {
      await fetch(`${API_BASE_URL}/system/resources/${id}/activate`, {
        method: 'POST',
      })
    }
  },
  diagnostics: {
    optimizePrompt: async (data: any) => {
      const res = await fetch(`${API_BASE_URL}/diagnostics/optimize-prompt`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    },
    generateImage: async (data: any) => {
      const res = await fetch(`${API_BASE_URL}/diagnostics/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    },
    generateVideo: async (data: any) => {
      const res = await fetch(`${API_BASE_URL}/diagnostics/generate-video`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      return res.json()
    }
  }
}
