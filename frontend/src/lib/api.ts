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
    list: async (): Promise<Project[]> => {
      const res = await fetch(`${API_BASE_URL}/projects`)
      return res.json()
    },
    create: async (project: any): Promise<Project> => {
      const res = await fetch(`${API_BASE_URL}/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(project),
      })
      return res.json()
    },
    update: async (id: string, updates: any): Promise<void> => {
      await fetch(`${API_BASE_URL}/projects/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
    },
    delete: async (id: string): Promise<void> => {
      await fetch(`${API_BASE_URL}/projects/${id}`, {
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
