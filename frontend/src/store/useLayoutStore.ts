import { create } from 'zustand'

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
  theme: 'dark',
  toggleSidebar: () => set((state) => ({ isSidebarOpen: !state.isSidebarOpen })),
  toggleCollapse: () => set((state) => ({ isSidebarCollapsed: !state.isSidebarCollapsed, expandedSubmenus: [] })),
  setSidebarOpen: (open: boolean) => set({ isSidebarOpen: open }),
  toggleSubmenu: (name: string) => set((state) => ({
    expandedSubmenus: state.expandedSubmenus.includes(name)
      ? state.expandedSubmenus.filter(s => s !== name)
      : [...state.expandedSubmenus, name]
  })),
  toggleTheme: () => set((state) => ({ theme: state.theme === 'light' ? 'dark' : 'light' })),
}))
