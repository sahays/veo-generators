import { create } from 'zustand'
import type { Project, SelectCategory, CustomOption } from '@/types/project'
import { DEFAULT_OPTIONS } from '@/types/project'
import { SEED_PROJECTS } from '@/lib/mockData'

interface ProjectState {
  projects: Project[]
  activeProjectId: string | null
  customOptions: Record<SelectCategory, CustomOption[]>
  view: 'list' | 'form'

  setView: (view: 'list' | 'form') => void
  setActiveProject: (id: string | null) => void
  addProject: (project: Project) => void
  updateProject: (id: string, updates: Partial<Project>) => void
  deleteProject: (id: string) => void
  addCustomOption: (category: SelectCategory, name: string, prompt: string) => void
  removeCustomOption: (category: SelectCategory, id: string) => void
  getOptions: (category: SelectCategory) => string[]
  getCustomOptions: (category: SelectCategory) => CustomOption[]
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: SEED_PROJECTS,
  activeProjectId: null,
  customOptions: {
    directorStyle: [],
    cameraMovement: [],
    mood: [],
    location: [],
    characterAppearance: [],
  },
  view: 'list',

  setView: (view) => set({ view }),

  setActiveProject: (id) => set({ activeProjectId: id }),

  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects] })),

  updateProject: (id, updates) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.id === id ? { ...p, ...updates, updatedAt: Date.now() } : p,
      ),
    })),

  deleteProject: (id) =>
    set((state) => ({
      projects: state.projects.filter((p) => p.id !== id),
      activeProjectId:
        state.activeProjectId === id ? null : state.activeProjectId,
    })),

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
