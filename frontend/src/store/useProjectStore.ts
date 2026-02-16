import { create } from 'zustand'
import type { Scene, ProjectFormData, SelectCategory, CustomOption } from '@/types/project'
import { DEFAULT_OPTIONS } from '@/types/project'

interface ProjectState {
  activeProjectId: string | null
  customOptions: Record<SelectCategory, CustomOption[]>
  tempProjectData: Partial<ProjectFormData> & { id?: string, scenes?: Scene[], mediaFiles?: any[] } | null

  setTempProjectData: (data: Partial<ProjectFormData> & { id?: string, scenes?: Scene[], mediaFiles?: any[] } | null) => void
  setActiveProject: (id: string | null) => void

  // Scene actions
  addScene: () => void
  updateScene: (sceneId: string, updates: Partial<Scene>) => void

  // Custom Options actions
  addCustomOption: (category: SelectCategory, name: string, prompt: string) => void
  removeCustomOption: (category: SelectCategory, id: string) => void
  getOptions: (category: SelectCategory) => string[]
  getCustomOptions: (category: SelectCategory) => CustomOption[]
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  activeProjectId: null,
  customOptions: {
    directorStyle: [],
    cameraMovement: [],
    mood: [],
    location: [],
    characterAppearance: [],
  },
  tempProjectData: null,

  setTempProjectData: (data) => set({ tempProjectData: data }),

  setActiveProject: (id) => set({ activeProjectId: id }),

  addScene: () =>
    set((state) => {
      if (!state.tempProjectData) return state
      const currentScenes = state.tempProjectData.scenes || []
      const newScene: Scene = {
        id: `s-${Date.now()}`,
        visual_description: '',
        timestamp_start: '00:00',
        timestamp_end: '00:05',
        metadata: { location: 'New Set' },
        tokens_consumed: { input: 0, output: 0 }
      }
      return {
        tempProjectData: {
          ...state.tempProjectData,
          scenes: [...currentScenes, newScene]
        }
      }
    }),

  updateScene: (sceneId, updates) =>
    set((state) => {
      if (!state.tempProjectData) return state
      const updatedScenes = state.tempProjectData.scenes?.map(s =>
        s.id === sceneId ? { ...s, ...updates } : s
      )
      return {
        tempProjectData: { ...state.tempProjectData, scenes: updatedScenes }
      }
    }),

  addCustomOption: (category, name, prompt) =>
    set((state) => ({
      customOptions: {
        ...state.customOptions,
        [category]: [
          ...state.customOptions[category],
          {
            id: `opt-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            name,
            prompt,
            category,
            createdAt: Date.now(),
          },
        ],
      },
    })),

  removeCustomOption: (category, id) =>
    set((state) => ({
      customOptions: {
        ...state.customOptions,
        [category]: state.customOptions[category].filter((o) => o.id !== id),
      },
    })),

  getOptions: (category) => {
    const state = get()
    return [
      ...DEFAULT_OPTIONS[category],
      ...state.customOptions[category].map((o) => o.name),
    ]
  },

  getCustomOptions: (category) => {
    return get().customOptions[category]
  },
}))
