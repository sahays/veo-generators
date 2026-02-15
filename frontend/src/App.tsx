import { Routes, Route, Navigate } from 'react-router-dom'
import { Sidebar } from './components/Layout'
import { ConfigSettingsPage } from './components/pages/ConfigSettingsPage'
import { ProjectForm } from './components/ads/ProjectForm'
import { RefinePromptView } from './components/ads/RefinePromptView'
import { ProductionSummary } from './components/ads/ProductionSummary'
import { ProjectList } from './components/ads/ProjectList'
import { DiagnosticsPage } from './components/pages/DiagnosticsPage'

function App() {
  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-6 md:p-8">
          <Routes>
            <Route path="/" element={<Navigate to="/productions" replace />} />
            
            {/* Productions Routes */}
            <Route path="/productions" element={<ProjectList />} />
            <Route path="/productions/new" element={<ProjectForm />} />
            <Route path="/productions/:id" element={<ProductionSummary />} />
            <Route path="/productions/:id/edit" element={<ProjectForm />} />
            <Route path="/productions/:id/script" element={<RefinePromptView />} />

            {/* Diagnostics */}
            <Route path="/diagnostics" element={<DiagnosticsPage />} />

            {/* Configuration Routes */}
            <Route path="/configuration/:category" element={<ConfigSettingsWrapper />} />
            
            {/* Fallback */}
            <Route path="*" element={<Navigate to="/productions" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

// Wrapper to handle the category param for the existing component
import { useParams } from 'react-router-dom'
import { SelectCategory } from './types/project'

const ConfigSettingsWrapper = () => {
  const { category } = useParams<{ category: string }>()
  return <ConfigSettingsPage category={category as SelectCategory} />
}

export default App
