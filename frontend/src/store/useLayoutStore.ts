import { create } from 'zustand'

export type PageId =
  | 'dashboard'
  | 'ads-generation'
  | 'highlights'
  | 'thumbnails'
  | 'orientations'
  | 'config-prompts'
  | 'config-documents'
  | 'config-director'
  | 'config-camera'
  | 'config-mood'
  | 'config-location'
  | 'config-character'

interface LayoutState {
  isSidebarOpen: boolean
  isSidebarCollapsed: boolean
  expandedSubmenus: string[]
  theme: 'light' | 'dark'
  activePage: PageId
  toggleSidebar: () => void
  toggleCollapse: () => void
  setSidebarOpen: (open: boolean) => void
  toggleSubmenu: (name: string) => void
  toggleTheme: () => void
  setActivePage: (page: PageId) => void
}

export const useLayoutStore = create<LayoutState>((set) => ({
  isSidebarOpen: false,
  isSidebarCollapsed: false,
  expandedSubmenus: [],
  theme: 'dark',
  activePage: 'dashboard',
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  toggleCollapse: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed, expandedSubmenus: [] })),
  setSidebarOpen: (open: boolean) => set({ isSidebarOpen: open }),
  toggleSubmenu: (name: string) => set((state) => ({
    expandedSubmenus: state.expandedSubmenus.includes(name)
      ? state.expandedSubmenus.filter(s => s !== name)
      : [...state.expandedSubmenus, name]
  })),
  toggleTheme: () => set((state) => ({ theme: state.theme === 'light' ? 'dark' : 'light' })),
  setActivePage: (page: PageId) => set({ activePage: page }),
}))
