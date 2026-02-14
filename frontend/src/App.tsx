import { AnimatePresence } from 'framer-motion'
import { Navbar, Sidebar } from './components/Layout'
import { DashboardPage } from './components/pages/DashboardPage'
import { AdsGenerationPage } from './components/pages/AdsGenerationPage'
import { ConfigSettingsPage } from './components/pages/ConfigSettingsPage'
import { useLayoutStore, type PageId } from './store/useLayoutStore'
import type { SelectCategory } from './types/project'

const CONFIG_PAGE_MAP: Partial<Record<PageId, SelectCategory>> = {
  'config-director': 'directorStyle',
  'config-camera': 'cameraMovement',
  'config-mood': 'mood',
  'config-location': 'location',
  'config-character': 'characterAppearance',
}

function App() {
  const activePage = useLayoutStore((s) => s.activePage)
  const configCategory = CONFIG_PAGE_MAP[activePage]

  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Navbar />
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-6 md:p-8">
          <AnimatePresence mode="wait">
            {activePage === 'dashboard' && <DashboardPage key="dashboard" />}
            {activePage === 'ads-generation' && <AdsGenerationPage key="ads-generation" />}
            {configCategory && (
              <ConfigSettingsPage key={activePage} category={configCategory} />
            )}
          </AnimatePresence>
        </main>
      </div>
    </div>
  )
}

export default App
