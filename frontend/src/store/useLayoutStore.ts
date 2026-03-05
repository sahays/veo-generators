import { create } from 'zustand'

export type ProjectView = 'list' | 'form' | 'review' | 'summary'

function getInitialTheme(): 'light' | 'dark' {
  try {
    const stored = localStorage.getItem('theme')
    if (stored === 'light' || stored === 'dark') return stored
  } catch {}
  return 'dark'
}

interface LayoutState {
  isSidebarOpen: boolean
  isSidebarCollapsed: boolean
  expandedSubmenus: string[]
  theme: 'light' | 'dark'
  toggleSidebar: () => void
  toggleCollapse: () => void
  setSidebarOpen: (open: boolean) => void
  toggleSubmenu: (name: string) => void
  toggleTheme: () => void
}

export const useLayoutStore = create<LayoutState>((set) => ({
  isSidebarOpen: false,
  isSidebarCollapsed: false,
  expandedSubmenus: [],
  theme: getInitialTheme(),
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  toggleCollapse: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed, expandedSubmenus: [] })),
  setSidebarOpen: (open: boolean) => set({ isSidebarOpen: open }),
  toggleSubmenu: (name: string) => set((state) => ({
    expandedSubmenus: state.expandedSubmenus.includes(name)
      ? state.expandedSubmenus.filter(s => s !== name)
      : [...state.expandedSubmenus, name]
  })),
  toggleTheme: () => set((state) => {
    const next = state.theme === 'light' ? 'dark' : 'light'
    try { localStorage.setItem('theme', next) } catch {}
    return { theme: next }
  }),
}))
