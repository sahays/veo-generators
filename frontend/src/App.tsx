import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
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
import { ChatPage } from './components/pages/ChatPage'
import { ThumbnailsLandingPage } from './components/pages/ThumbnailsLandingPage'
import { ThumbnailsWorkPage } from './components/pages/ThumbnailsWorkPage'
import { ReframeLandingPage } from './components/pages/ReframeLandingPage'
import { ReframeWorkPage } from './components/pages/ReframeWorkPage'
import { ReframeOutputPage } from './components/pages/ReframeOutputPage'
import { PromoLandingPage } from './components/pages/PromoLandingPage'
import { PromoWorkPage } from './components/pages/PromoWorkPage'
import { AdaptsLandingPage } from './components/pages/AdaptsLandingPage'
import { AdaptsWorkPage } from './components/pages/AdaptsWorkPage'
import { AdaptsOutputPage } from './components/pages/AdaptsOutputPage'
import { UploadsPage } from './components/pages/UploadsPage'
import { InviteCodesPage } from './components/pages/InviteCodesPage'
import { ModelsPage } from './components/pages/ModelsPage'
import { AvatarLandingPage } from './components/pages/AvatarLandingPage'
import { AvatarCreatePage } from './components/pages/AvatarCreatePage'
import { AvatarWorkPage } from './components/pages/AvatarWorkPage'
import { InviteCodeGate } from './components/InviteCodeGate'
import { ChatWidget } from './components/chat/ChatWidget'
import { useAuthStore } from './store/useAuthStore'
import { api } from './lib/api'

const GUEST_INVITE_CODE = (import.meta.env.VITE_GUEST_INVITE_CODE as string | undefined) || ''

function App() {
  const { isAuthenticated, isMaster, isPower, inviteCode, login, logout } = useAuthStore()
  // Power users have full feature access except invite-code management.
  const canWrite = isMaster || isPower
  const [guestLoginPending, setGuestLoginPending] = useState(false)

  useEffect(() => {
    if (isAuthenticated && inviteCode) {
      // Re-validate the persisted code in the background.
      api.auth.validate(inviteCode).then((result) => {
        if (!result.valid) {
          logout()
          if (GUEST_INVITE_CODE) tryGuestLogin()
        } else {
          // Refresh role flags in case the code was promoted/demoted.
          login(inviteCode, result.is_master, result.is_power)
        }
      }).catch(() => {
        // Network error — don't logout, let subsequent API calls handle it.
      })
      return
    }
    if (GUEST_INVITE_CODE) tryGuestLogin()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const tryGuestLogin = async () => {
    setGuestLoginPending(true)
    try {
      const result = await api.auth.validate(GUEST_INVITE_CODE)
      if (result.valid) {
        login(GUEST_INVITE_CODE, result.is_master, result.is_power)
      }
    } catch {
      // Fall back to the gate.
    } finally {
      setGuestLoginPending(false)
    }
  }

  // Auto-scroll to hash anchor (retry for async content)
  const { hash } = useLocation()
  useEffect(() => {
    if (!hash) return
    const id = hash.slice(1)
    let attempts = 0
    const tryScroll = () => {
      const el = document.getElementById(id)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      } else if (attempts < 10) {
        attempts++
        setTimeout(tryScroll, 300)
      }
    }
    tryScroll()
  }, [hash])

  if (!isAuthenticated) {
    if (GUEST_INVITE_CODE && guestLoginPending) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-background">
          <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
        </div>
      )
    }
    return <InviteCodeGate />
  }

  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-6 md:p-8">
          <div className="max-w-4xl mx-auto w-full">
            <Routes>
              <Route path="/" element={<Navigate to={canWrite ? '/chat' : '/productions'} replace />} />

              {/* AI Co-Pilot / Ask Aanya — master & power users */}
              <Route
                path="/chat"
                element={canWrite ? <ChatPage /> : <Navigate to="/productions" replace />}
              />

              {/* Productions Routes — :id pages readable; /new and /:id/edit are write flows */}
              <Route path="/productions" element={<ProjectList />} />
              <Route path="/productions/new" element={canWrite ? <ProjectForm /> : <Navigate to="/productions" replace />} />
              <Route path="/productions/:id" element={<ProductionSummary />} />
              <Route path="/productions/:id/edit" element={canWrite ? <ProjectForm /> : <Navigate to="/productions" replace />} />
              <Route path="/productions/:id/script" element={<RefinePromptView />} />

              {/* Key Moments */}
              <Route path="/key-moments" element={<KeyMomentsLandingPage />} />
              <Route path="/key-moments/analyze" element={canWrite ? <KeyMomentsAnalyzePage /> : <Navigate to="/key-moments" replace />} />
              <Route path="/key-moments/:id" element={<KeyMomentsAnalyzePage />} />

              {/* Thumbnails */}
              <Route path="/thumbnails" element={<ThumbnailsLandingPage />} />
              <Route path="/thumbnails/create" element={canWrite ? <ThumbnailsWorkPage /> : <Navigate to="/thumbnails" replace />} />
              <Route path="/thumbnails/:id" element={<ThumbnailsWorkPage />} />

              {/* Orientations / Reframe */}
              <Route path="/orientations" element={<ReframeLandingPage />} />
              <Route path="/orientations/create" element={canWrite ? <ReframeWorkPage /> : <Navigate to="/orientations" replace />} />
              <Route path="/orientations/:id" element={<ReframeWorkPage />} />
              <Route path="/orientations/:id/:section" element={<ReframeOutputPage />} />

              {/* Promos */}
              <Route path="/promos" element={<PromoLandingPage />} />
              <Route path="/promos/create" element={canWrite ? <PromoWorkPage /> : <Navigate to="/promos" replace />} />
              <Route path="/promos/:id" element={<PromoWorkPage />} />

              {/* Avatars — master & power users (Vertex Live allowlist-pending) */}
              <Route path="/avatars" element={canWrite ? <AvatarLandingPage /> : <Navigate to="/productions" replace />} />
              <Route path="/avatars/create" element={canWrite ? <AvatarCreatePage /> : <Navigate to="/productions" replace />} />
              <Route path="/avatars/:id" element={canWrite ? <AvatarWorkPage /> : <Navigate to="/productions" replace />} />

              {/* Adapts */}
              <Route path="/adapts" element={<AdaptsLandingPage />} />
              <Route path="/adapts/create" element={canWrite ? <AdaptsWorkPage /> : <Navigate to="/adapts" replace />} />
              <Route path="/adapts/:id" element={<AdaptsWorkPage />} />
              <Route path="/adapts/:id/prompt" element={<AdaptsOutputPage />} />
              <Route path="/adapts/:id/prompt/:variantIndex" element={<AdaptsOutputPage />} />

              {/* Settings — Files & Prompts readable by all */}
              <Route path="/uploads" element={<UploadsPage />} />
              <Route path="/uploads/:id" element={<UploadsPage />} />
              <Route path="/prompts" element={<PromptsPage />} />
              <Route path="/prompts/:id" element={<PromptDetailPage />} />

              {/* Settings — master & power users */}
              {canWrite && (
                <>
                  <Route path="/models" element={<ModelsPage />} />
                  <Route path="/diagnostics" element={<DiagnosticsPage />} />
                </>
              )}

              {/* Invite codes — master only */}
              {isMaster && (
                <Route path="/invite-codes" element={<InviteCodesPage />} />
              )}

              {/* Fallback */}
              <Route path="*" element={<Navigate to="/productions" replace />} />
            </Routes>
          </div>
        </main>
      </div>
      {canWrite && <ChatWidget />}
    </div>
  )
}

export default App
