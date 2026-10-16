import { motion, AnimatePresence } from 'framer-motion'
import {
  Menu, X, Clapperboard, Zap, Image as ImageIcon, Smartphone, Scissors, LayoutGrid,
  ChevronLeft, ChevronRight, Terminal, Bot, Settings, Cpu,
  FileText, Sun, Moon, Activity, Upload, Shield, LogOut, User, Languages,
} from 'lucide-react'
import { useLayoutStore } from '@/store/useLayoutStore'
import { useAuthStore } from '@/store/useAuthStore'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Button } from '@/components/ui/button'
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
  '/orientations/create': 'New Reframe',
  '/promos': 'Promos',
  '/promos/create': 'New Promo',
  '/adapts': 'Adapts',
  '/adapts/create': 'New Adapt',
  '/dubbing': 'Dubbing',
  '/dubbing/create': 'New Dub',
  '/invite-codes': 'Invite Codes',
  '/models': 'AI Models',
  '/chat': 'Ask Aanya',
  '/avatars': 'Avatars',
  '/avatars/create': 'New Avatar',
}

function getPageTitle(pathname: string): string {
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname]
  if (pathname.match(/^\/productions\/[^/]+\/script$/)) return 'Script Editor'
  if (pathname.match(/^\/productions\/[^/]+\/edit$/)) return 'Edit Production'
  if (pathname.match(/^\/productions\/[^/]+$/)) return 'Production Details'
  if (pathname.match(/^\/key-moments\/[^/]+$/)) return 'Key Moments Analysis'
  if (pathname.match(/^\/thumbnails\/[^/]+$/)) return 'Thumbnail Details'
  if (pathname.match(/^\/orientations\/[^/]+$/)) return 'Reframe Details'
  if (pathname.match(/^\/promos\/[^/]+$/)) return 'Promo Details'
  if (pathname.match(/^\/adapts\/[^/]+\/prompt/)) return 'Adapt Prompt'
  if (pathname.match(/^\/adapts\/[^/]+$/)) return 'Adapt Details'
  if (pathname.match(/^\/dubbing\/[^/]+$/)) return 'Dub Details'
  if (pathname.match(/^\/uploads\/[^/]+$/)) return 'File Details'
  if (pathname.match(/^\/prompts\/[^/]+$/)) return 'Prompt Details'
  if (pathname.match(/^\/avatars\/[^/]+$/)) return 'Avatar'
  return 'VeoGen'
}

const SidebarNavLink = ({
  item,
  collapsed,
  onSelect,
}: {
  item: NavItem
  collapsed: boolean
  onSelect: () => void
}) => {
  const linkEl = (
    <NavLink
      to={item.path}
      onClick={onSelect}
      className={({ isActive }) =>
        cn(
          'relative flex items-center rounded-[6px] transition-all duration-200 group cursor-pointer overflow-hidden',
          collapsed
            ? 'h-10 w-10 mx-auto justify-center px-0'
            : 'h-9 w-full px-3 gap-3',
          isActive
            ? 'text-accent font-semibold'
            : 'text-sidebar-text/80 hover:bg-orange-500/8 hover:text-sidebar-text',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.div
              layoutId="sidebar-active-pill"
              transition={{ type: 'spring', stiffness: 420, damping: 32 }}
              className="absolute inset-0 rounded-[6px] bg-gradient-to-r from-orange-500/18 via-orange-500/10 to-amber-500/5 border border-orange-500/30 shadow-[0_2px_10px_-2px_rgba(249,115,22,0.18)] pointer-events-none"
            />
          )}
          {isActive && (
            <motion.div
              layoutId="sidebar-active-bar"
              transition={{ type: 'spring', stiffness: 420, damping: 32 }}
              className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full bg-gradient-to-b from-orange-400 to-orange-600 pointer-events-none"
            />
          )}
          <item.icon
            size={18}
            className={cn(
              'relative z-10 shrink-0 transition-transform duration-200 group-hover:scale-105',
              isActive && 'text-accent',
            )}
          />
          {!collapsed && (
            <span className="relative z-10 text-sm font-medium truncate">
              {item.name}
            </span>
          )}
        </>
      )}
    </NavLink>
  )

  if (!collapsed) return linkEl

  return (
    <Tooltip>
      <TooltipTrigger asChild>{linkEl}</TooltipTrigger>
      <TooltipContent side="right">{item.name}</TooltipContent>
    </Tooltip>
  )
}

export const Sidebar = () => {
  const {
    isSidebarCollapsed,
    toggleCollapse,
    isSidebarOpen,
    setSidebarOpen,
    theme,
    toggleTheme,
  } = useLayoutStore()
  const { isMaster, isPower, logout } = useAuthStore()
  const canWrite = isMaster || isPower

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
    ...(canWrite ? [{ name: 'Ask Aanya', icon: Bot, path: '/chat' }] : []),
    ...(canWrite ? [{ name: 'Avatars', icon: User, path: '/avatars' }] : []),
    { name: 'Productions', icon: Clapperboard, path: '/productions' },
    { name: 'Key Moments', icon: Zap, path: '/key-moments' },
    { name: 'Thumbnails', icon: ImageIcon, path: '/thumbnails' },
    { name: 'Orientations', icon: Smartphone, path: '/orientations' },
    { name: 'Promos', icon: Scissors, path: '/promos' },
    { name: 'Adapts', icon: LayoutGrid, path: '/adapts' },
    { name: 'Dubbing', icon: Languages, path: '/dubbing' },
  ]

  const settingsItems: NavItem[] = [
    { name: 'Files', icon: Upload, path: '/uploads' },
    { name: 'System Prompts', icon: FileText, path: '/prompts' },
    ...(canWrite
      ? [
          { name: 'Models', icon: Cpu, path: '/models' },
          { name: 'Diagnostics', icon: Activity, path: '/diagnostics' },
        ]
      : []),
    ...(isMaster ? [{ name: 'Invite Codes', icon: Shield, path: '/invite-codes' }] : []),
  ]

  return (
    <>
      {/* Mobile Floating Menu Trigger */}
      {!isSidebarOpen && (
        <Button
          variant="outline"
          size="icon"
          onClick={() => setSidebarOpen(true)}
          className="fixed top-4 left-4 z-30 lg:hidden bg-card/90 backdrop-blur shadow-lg"
          aria-label="Open navigation menu"
        >
          <Menu size={18} />
        </Button>
      )}

      {/* Mobile Overlay */}
      <AnimatePresence>
        {isSidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setSidebarOpen(false)}
            className="fixed inset-0 bg-black/55 z-40 lg:hidden backdrop-blur-sm"
          />
        )}
      </AnimatePresence>

      {/* Sidebar Content */}
      <motion.aside
        animate={{
          width: isSidebarCollapsed ? '68px' : '256px',
          x: 0,
        }}
        initial={false}
        transition={{ type: 'spring', stiffness: 360, damping: 32 }}
        className={cn(
          'fixed left-0 top-0 h-full text-sidebar-text z-50 flex flex-col transition-colors duration-300',
          'lg:relative animate-gradient-stealth glass shadow-2xl overflow-hidden',
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0',
        )}
      >
        <div
          className={cn(
            'border-b border-sidebar-text/8 flex items-center',
            isSidebarCollapsed
              ? 'flex-col justify-center gap-2 px-2 py-3'
              : 'justify-between px-4 py-3.5',
          )}
        >
          {!isSidebarCollapsed ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-2.5"
            >
              <div className="p-1.5 rounded-[6px] bg-gradient-to-br from-orange-500/20 to-amber-500/10 border border-orange-500/25">
                <GoogleLogo size={18} />
              </div>
              <h2 className="text-lg font-heading font-bold tracking-tight">VeoGen</h2>
            </motion.div>
          ) : (
            <div className="p-1.5 rounded-[6px] bg-gradient-to-br from-orange-500/20 to-amber-500/10 border border-orange-500/25">
              <GoogleLogo size={18} />
            </div>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleCollapse}
            className="hidden lg:inline-flex h-7 w-7 text-sidebar-text/75 hover:text-sidebar-text"
            title={isSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {isSidebarCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setSidebarOpen(false)}
            className="lg:hidden h-7 w-7 text-sidebar-text/75 hover:text-sidebar-text"
          >
            <X size={17} />
          </Button>
        </div>

        <nav
          className={cn(
            'flex-1 py-3 overflow-y-auto no-scrollbar space-y-1',
            isSidebarCollapsed ? 'px-2' : 'px-3',
          )}
        >
          {navItems.map((item) => (
            <SidebarNavLink
              key={item.name}
              item={item}
              collapsed={isSidebarCollapsed}
              onSelect={() => setSidebarOpen(false)}
            />
          ))}

          <div
            className={cn(
              'flex items-center gap-2 pt-4 pb-1',
              isSidebarCollapsed ? 'justify-center px-0' : 'px-3',
            )}
          >
            {isSidebarCollapsed ? (
              <Settings size={14} className="opacity-40" />
            ) : (
              <span className="text-[10px] font-bold uppercase tracking-widest opacity-45">
                Settings
              </span>
            )}
          </div>
          {settingsItems.map((item) => (
            <SidebarNavLink
              key={item.name}
              item={item}
              collapsed={isSidebarCollapsed}
              onSelect={() => setSidebarOpen(false)}
            />
          ))}
        </nav>

        <div
          className={cn(
            'py-3 border-t border-sidebar-text/10 flex flex-col gap-1',
            isSidebarCollapsed ? 'px-2' : 'px-3',
          )}
        >
          <Button
            variant="ghost"
            onClick={toggleTheme}
            className={cn(
              'rounded-[6px] text-sidebar-text/85 hover:text-sidebar-text',
              isSidebarCollapsed
                ? 'h-10 w-10 mx-auto justify-center p-0'
                : 'h-9 w-full justify-start px-3 gap-3',
            )}
          >
            {theme === 'light' ? (
              <Moon size={18} className="text-orange-600 transition-transform group-hover:rotate-12 shrink-0" />
            ) : (
              <Sun size={18} className="text-orange-400 transition-transform group-hover:rotate-45 shrink-0" />
            )}
            {!isSidebarCollapsed && (
              <span className="text-sm font-medium">
                {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
              </span>
            )}
          </Button>
          <Button
            variant="ghost"
            onClick={logout}
            className={cn(
              'rounded-[6px] text-sidebar-text/85 hover:bg-red-500/15 hover:text-red-500 hover:border-red-500/25',
              isSidebarCollapsed
                ? 'h-10 w-10 mx-auto justify-center p-0'
                : 'h-9 w-full justify-start px-3 gap-3',
            )}
          >
            <LogOut size={18} className="shrink-0" />
            {!isSidebarCollapsed && <span className="text-sm font-medium">Sign Out</span>}
          </Button>
        </div>
      </motion.aside>
    </>
  )
}
