import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Sidebar } from './components/Layout'
import { ProjectForm } from './components/ads/ProjectForm'
import { RefinePromptView } from './components/ads/RefinePromptView'
import { ProductionSummary } from './components/ads/ProductionSummary'
import { ProjectList } from './components/ads/ProjectList'
import { DiagnosticsPage } from './components/pages/DiagnosticsPage'
import { PromptsPage } from './components/pages/PromptsPage'
import { PromptDetailPage } from './components/pages/PromptDetailPage'
import { KeyMomentsLandingPage } from './components/pages/KeyMomentsLandingPage'
import { KeyMomentsAnalyzePage } from './components/pages/KeyMomentsAnalyzePage'
import { ThumbnailsLandingPage } from './components/pages/ThumbnailsLandingPage'
import { ThumbnailsWorkPage } from './components/pages/ThumbnailsWorkPage'
import { ReframeLandingPage } from './components/pages/ReframeLandingPage'
import { ReframeWorkPage } from './components/pages/ReframeWorkPage'
import { PromoLandingPage } from './components/pages/PromoLandingPage'
import { PromoWorkPage } from './components/pages/PromoWorkPage'
import { UploadsPage } from './components/pages/UploadsPage'
import { InviteCodesPage } from './components/pages/InviteCodesPage'
import { InviteCodeGate } from './components/InviteCodeGate'
import { useAuthStore } from './store/useAuthStore'
import { api } from './lib/api'

function App() {
  const { isAuthenticated, isMaster, inviteCode, logout } = useAuthStore()

  useEffect(() => {
    if (!isAuthenticated || !inviteCode) return
    api.auth.validate(inviteCode).then((result) => {
      if (!result.valid) logout()
    }).catch(() => {
      // Network error — don't logout, let subsequent API calls handle it
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!isAuthenticated) {
    return <InviteCodeGate />
  }

  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-6 md:p-8">
          <div className="max-w-4xl mx-auto w-full">
            <Routes>
              <Route path="/" element={<Navigate to="/productions" replace />} />

              {/* Productions Routes */}
              <Route path="/productions" element={<ProjectList />} />
              <Route path="/productions/new" element={<ProjectForm />} />
              <Route path="/productions/:id" element={<ProductionSummary />} />
              <Route path="/productions/:id/edit" element={<ProjectForm />} />
              <Route path="/productions/:id/script" element={<RefinePromptView />} />

              {/* Key Moments */}
              <Route path="/key-moments" element={<KeyMomentsLandingPage />} />
              <Route path="/key-moments/analyze" element={<KeyMomentsAnalyzePage />} />
              <Route path="/key-moments/:id" element={<KeyMomentsAnalyzePage />} />

              {/* Thumbnails */}
              <Route path="/thumbnails" element={<ThumbnailsLandingPage />} />
              <Route path="/thumbnails/create" element={<ThumbnailsWorkPage />} />
              <Route path="/thumbnails/:id" element={<ThumbnailsWorkPage />} />

              {/* Orientations / Reframe */}
              <Route path="/orientations" element={<ReframeLandingPage />} />
              <Route path="/orientations/create" element={<ReframeWorkPage />} />
              <Route path="/orientations/:id" element={<ReframeWorkPage />} />

              {/* Promos */}
              <Route path="/promos" element={<PromoLandingPage />} />
              <Route path="/promos/create" element={<PromoWorkPage />} />
              <Route path="/promos/:id" element={<PromoWorkPage />} />

              {/* Uploads */}
              <Route path="/uploads" element={<UploadsPage />} />
              <Route path="/uploads/:id" element={<UploadsPage />} />

              {/* System Prompts (view for all, edit for master) */}
              <Route path="/prompts" element={<PromptsPage />} />
              <Route path="/prompts/:id" element={<PromptDetailPage />} />

              {/* Admin (master only) */}
              {isMaster && (
                <>
                  <Route path="/diagnostics" element={<DiagnosticsPage />} />
                  <Route path="/invite-codes" element={<InviteCodesPage />} />
                </>
              )}

              {/* Fallback */}
              <Route path="*" element={<Navigate to="/productions" replace />} />
            </Routes>
          </div>
        </main>
      </div>
    </div>
  )
}

export default App
