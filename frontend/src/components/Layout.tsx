import { motion, AnimatePresence } from 'framer-motion'
import { 
  Menu, X, Megaphone, Zap, Image as ImageIcon, Smartphone, 
  ChevronLeft, ChevronRight, LogOut, Settings, Terminal, 
  FileText, Library, ChevronDown, Sun, Moon
} from 'lucide-react'
import { useLayoutStore } from '@/store/useLayoutStore'
import { cn } from '@/lib/utils'
import { useEffect } from 'react'

export const Sidebar = () => {
  const { 
    isSidebarCollapsed, toggleCollapse, isSidebarOpen, 
    setSidebarOpen, expandedSubmenus, toggleSubmenu 
  } = useLayoutStore()

  const navItems = [
    { name: 'Ads generation', icon: Megaphone, href: '#' },
    { name: 'Highlights', icon: Zap, href: '#' },
    { name: 'Thumbnails', icon: ImageIcon, href: '#' },
    { name: 'Orientations', icon: Smartphone, href: '#' },
    { 
      name: 'Configuration', 
      icon: Settings, 
      subItems: [
        { name: 'Prompts', icon: Terminal, href: '#' },
        { name: 'Documents', icon: FileText, href: '#' },
        { name: 'Assets', icon: Library, href: '#' },
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
          width: isSidebarCollapsed ? '70px' : '260px',
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

            return (
              <div key={item.name}>
                <motion.button
                  onClick={() => hasSubItems && !isSidebarCollapsed && toggleSubmenu(item.name)}
                  className={cn(
                    "flex items-center gap-4 w-full px-6 py-3 transition-all duration-200 group cursor-pointer",
                    "hover:bg-accent hover:text-slate-900",
                    isSidebarCollapsed && "justify-center px-0"
                  )}
                >
                  <item.icon size={20} className="shrink-0 transition-colors" />
                  {!isSidebarCollapsed && (
                    <div className="flex-1 flex items-center justify-between">
                      <span className="text-sm font-medium">{item.name}</span>
                      {hasSubItems && (
                        <motion.div
                          animate={{ rotate: isExpanded ? 180 : 0 }}
                          transition={{ duration: 0.2 }}
                        >
                          <ChevronDown size={14} />
                        </motion.div>
                      )}
                    </div>
                  )}
                </motion.button>

                {!isSidebarCollapsed && hasSubItems && (
                  <AnimatePresence>
                    {isExpanded && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden bg-white/5"
                      >
                        {item.subItems.map((sub) => (
                          <motion.a
                            key={sub.name}
                            href={sub.href}
                            className={cn(
                              "flex items-center gap-3 pl-12 pr-6 py-2.5 text-xs font-medium transition-all duration-200 cursor-pointer",
                              "hover:bg-accent/80 hover:text-slate-900"
                            )}
                          >
                            <sub.icon size={16} />
                            <span>{sub.name}</span>
                          </motion.a>
                        ))}
                      </motion.div>
                    )}
                  </AnimatePresence>
                )}
              </div>
            )
          })}
        </nav>

        <div className="border-t border-white/5">
          <motion.button
            className={cn(
              "flex items-center gap-4 w-full px-6 py-4 transition-all duration-200 cursor-pointer group",
              "hover:bg-accent hover:text-slate-900",
              isSidebarCollapsed && "justify-center px-0"
            )}
          >
            <LogOut size={20} className="shrink-0" />
            {!isSidebarCollapsed && <span className="text-sm font-medium">Logout</span>}
          </motion.button>
        </div>
      </motion.aside>
    </>
  )
}

export const Navbar = () => {
  const { toggleSidebar, theme, toggleTheme } = useLayoutStore()

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  return (
    <header className="sticky top-0 z-30 w-full glass border-b border-border bg-background/60 backdrop-blur-md">
      <div className="flex h-14 items-center justify-between px-6">
        <div className="flex items-center gap-4">
          <button
            onClick={toggleSidebar}
            className="lg:hidden p-1.5 hover:bg-muted rounded-md cursor-pointer"
          >
            <Menu size={20} />
          </button>
          <h1 className="text-base font-heading font-semibold text-foreground">Dashboard</h1>
        </div>
        
        <div className="flex items-center gap-3">
          <button
            onClick={toggleTheme}
            className="p-1.5 hover:bg-muted rounded-md transition-colors cursor-pointer"
          >
            {theme === 'light' ? <Moon size={18} /> : <Sun size={18} />}
          </button>
          <div className="h-7 w-7 rounded-full bg-accent flex items-center justify-center text-slate-900 text-xs font-bold cursor-pointer">
            S
          </div>
        </div>
      </div>
    </header>
  )
}
