import { motion, AnimatePresence } from 'framer-motion'
import {
  Menu, X, Megaphone, Zap, Image as ImageIcon, Smartphone,
  ChevronLeft, ChevronRight, Terminal,
  FileText, Sun, Moon, Activity, Upload
} from 'lucide-react'
import { useLayoutStore } from '@/store/useLayoutStore'
import { cn } from '@/lib/utils'
import { useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'

interface NavItem {
  name: string
  icon: typeof Terminal
  path: string
}

const GoogleLogo = ({ size = 18 }: { size?: number }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} className="shrink-0">
    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
  </svg>
)

const PAGE_TITLES: Record<string, string> = {
  '/productions': 'Productions',
  '/productions/new': 'New Production',
  '/key-moments': 'Key Moments',
  '/key-moments/analyze': 'Analyze Key Moments',
  '/thumbnails': 'Thumbnails',
  '/thumbnails/create': 'Create Thumbnail',
  '/uploads': 'Files',
  '/prompts': 'System Prompts',
  '/diagnostics': 'Diagnostics',
  '/orientations': 'Orientations',
}

function getPageTitle(pathname: string): string {
  // Exact match first
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname]
  // Dynamic routes
  if (pathname.match(/^\/productions\/[^/]+\/script$/)) return 'Script Editor'
  if (pathname.match(/^\/productions\/[^/]+\/edit$/)) return 'Edit Production'
  if (pathname.match(/^\/productions\/[^/]+$/)) return 'Production Details'
  if (pathname.match(/^\/key-moments\/[^/]+$/)) return 'Key Moments Analysis'
  if (pathname.match(/^\/thumbnails\/[^/]+$/)) return 'Thumbnail Details'
  if (pathname.match(/^\/uploads\/[^/]+$/)) return 'File Details'
  return 'VeoGen'
}

export const Sidebar = () => {
  const {
    isSidebarCollapsed, toggleCollapse, isSidebarOpen,
    setSidebarOpen,
    theme, toggleTheme
  } = useLayoutStore()

  const location = useLocation()
  const pageTitle = getPageTitle(location.pathname)

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  useEffect(() => {
    document.title = pageTitle === 'VeoGen' ? 'VeoGen' : `${pageTitle} | VeoGen`
  }, [pageTitle])

  const navItems: NavItem[] = [
    { name: 'Movie Productions', icon: Megaphone, path: '/productions' },
    { name: 'Key Moments', icon: Zap, path: '/key-moments' },
    { name: 'Thumbnails', icon: ImageIcon, path: '/thumbnails' },
    { name: 'Files', icon: Upload, path: '/uploads' },
    { name: 'Orientations', icon: Smartphone, path: '/orientations' },
    { name: 'System Prompts', icon: FileText, path: '/prompts' },
    { name: 'Diagnostics', icon: Activity, path: '/diagnostics' },
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
          {!isSidebarCollapsed ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-2"
            >
              <GoogleLogo size={20} />
              <h2 className="text-lg font-heading font-bold tracking-tight">VeoGen</h2>
            </motion.div>
          ) : (
            <GoogleLogo size={22} />
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
          {navItems.map((item) => (
            <NavLink
              key={item.name}
              to={item.path}
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
          ))}
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
