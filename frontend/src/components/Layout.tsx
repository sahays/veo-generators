import { motion, AnimatePresence } from 'framer-motion'
import {
  Menu, X, Megaphone, Zap, Image as ImageIcon, Smartphone,
  ChevronLeft, ChevronRight, Settings, Terminal,
  FileText, ChevronDown, Sun, Moon,
  Clapperboard, Video, Palette, MapPin, User, Activity
} from 'lucide-react'
import { useLayoutStore } from '@/store/useLayoutStore'
import { cn } from '@/lib/utils'
import { useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

interface SubItem {
  name: string
  icon: typeof Terminal
  path: string
}

interface NavItem {
  name: string
  icon: typeof Terminal
  path?: string
  subItems?: SubItem[]
}

export const Sidebar = () => {
  const { 
    isSidebarCollapsed, toggleCollapse, isSidebarOpen, 
    setSidebarOpen, expandedSubmenus, toggleSubmenu,
    theme, toggleTheme
  } = useLayoutStore()

  const location = useLocation()

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  const navItems: NavItem[] = [
    { name: 'Movie Productions', icon: Megaphone, path: '/productions' },
    { name: 'Highlights', icon: Zap, path: '/highlights' },
    { name: 'Thumbnails', icon: ImageIcon, path: '/thumbnails' },
    { name: 'Orientations', icon: Smartphone, path: '/orientations' },
    { name: 'System Prompts', icon: FileText, path: '/prompts' },
    { name: 'Diagnostics', icon: Activity, path: '/diagnostics' },
    {
      name: 'Configuration',
      icon: Settings,
      subItems: [
        { name: 'Prompts', icon: Terminal, path: '/configuration/config-prompts' },
        { name: 'Documents', icon: FileText, path: '/configuration/config-documents' },
        { name: 'Director', icon: Clapperboard, path: '/configuration/config-director' },
        { name: 'Camera', icon: Video, path: '/configuration/config-camera' },
        { name: 'Mood', icon: Palette, path: '/configuration/config-mood' },
        { name: 'Location', icon: MapPin, path: '/configuration/config-location' },
        { name: 'Character', icon: User, path: '/configuration/config-character' },
      ]
    },
  ]

  return (
    <>
      {/* Mobile Overlay */}
      {isSidebarOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 bg-black/50 z-40 lg:hidden backdrop-blur-sm"
        />
      )}

      {/* Sidebar Content */}
      <motion.aside
        animate={{
          width: isSidebarCollapsed ? '80px' : '280px',
          x: 0
        }}
        initial={false}
        className={cn(
          "fixed left-0 top-0 h-full text-sidebar-text z-50 flex flex-col transition-all duration-300",
          "lg:relative animate-gradient-stealth glass shadow-2xl overflow-hidden",
          isSidebarOpen ? "translate-x-0" : "-translate-x-full lg:translate-x-0"
        )}
      >
        <div className="p-5 flex items-center justify-between">
          {!isSidebarCollapsed && (
            <motion.h2
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-lg font-heading font-bold tracking-tight"
            >
              VeoGen
            </motion.h2>
          )}
          <button
            onClick={toggleCollapse}
            className="hidden lg:flex p-1 hover:bg-white/10 rounded transition-colors cursor-pointer"
          >
            {isSidebarCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
          </button>
          <button
            onClick={() => setSidebarOpen(false)}
            className="lg:hidden p-1 hover:bg-white/10 rounded cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 py-4 overflow-y-auto no-scrollbar">
          {navItems.map((item) => {
            const hasSubItems = !!item.subItems
            const isExpanded = expandedSubmenus.includes(item.name)
            const isPathActive = item.path && location.pathname.startsWith(item.path)
            const hasActiveSub = item.subItems?.some(sub => location.pathname === sub.path)

            return (
              <div key={item.name}>
                {hasSubItems ? (
                  <motion.button
                    onClick={() => !isSidebarCollapsed && toggleSubmenu(item.name)}
                    className={cn(
                      "flex items-center gap-4 w-full px-6 py-3 transition-all duration-200 group cursor-pointer",
                      "hover:bg-accent hover:text-slate-900",
                      hasActiveSub && "bg-accent/20 text-accent",
                      isSidebarCollapsed && "justify-center px-0"
                    )}
                  >
                    <item.icon size={20} className="shrink-0 transition-colors" />
                    {!isSidebarCollapsed && (
                      <div className="flex-1 flex items-center justify-between">
                        <span className="text-sm font-medium">{item.name}</span>
                        <motion.div
                          animate={{ rotate: isExpanded ? 180 : 0 }}
                          transition={{ duration: 0.2 }}
                        >
                          <ChevronDown size={14} />
                        </motion.div>
                      </div>
                    )}
                  </motion.button>
                ) : (
                  <NavLink
                    to={item.path!}
                    onClick={() => setSidebarOpen(false)}
                    className={({ isActive }) => cn(
                      "flex items-center gap-4 w-full px-6 py-3 transition-all duration-200 group cursor-pointer",
                      "hover:bg-accent hover:text-slate-900",
                      isActive && "bg-accent text-slate-900",
                      isSidebarCollapsed && "justify-center px-0"
                    )}
                  >
                    <item.icon size={20} className="shrink-0 transition-colors" />
                    {!isSidebarCollapsed && (
                      <span className="text-sm font-medium">{item.name}</span>
                    )}
                  </NavLink>
                )}

                {!isSidebarCollapsed && hasSubItems && (
                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden bg-white/5"
                      >
                        {item.subItems!.map((sub) => (
                          <NavLink
                            key={sub.name}
                            to={sub.path}
                            onClick={() => setSidebarOpen(false)}
                            className={({ isActive }) => cn(
                              "flex items-center gap-3 pl-12 pr-6 py-2.5 text-xs font-medium transition-all duration-200 cursor-pointer w-full",
                              "hover:bg-accent/80 hover:text-slate-900",
                              isActive && "bg-accent text-slate-900"
                            )}
                          >
                            <sub.icon size={16} />
                            <span>{sub.name}</span>
                          </NavLink>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                )}
              </div>
            )
          })}
        </nav>

        <div className="p-4 border-t border-white/5 flex flex-col gap-2">
          <motion.button
            onClick={toggleTheme}
            whileTap={{ scale: 0.95 }}
            className={cn(
              "flex items-center gap-4 w-full p-3 rounded-xl transition-all duration-200 cursor-pointer group hover:bg-accent hover:text-slate-900",
              isSidebarCollapsed && "justify-center px-0"
            )}
          >
            {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
            {!isSidebarCollapsed && <span className="text-sm font-medium">{theme === 'light' ? 'Dark Mode' : 'Light Mode'}</span>}
          </motion.button>
        </div>
      </motion.aside>
    </>
  )
}
