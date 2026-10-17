import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Sidebar } from './components/Layout'
import { ProjectForm } from './components/ads/ProjectForm'
import { RefinePromptView } from './components/ads/RefinePromptView'
import { ProductionSummary } from './components/ads/ProductionSummary'
import { ProjectList } from './components/ads/ProjectList'
import { DiagnosticsPage } from './components/pages/admin/DiagnosticsPage'
import { PromptsPage } from './components/pages/PromptsPage'
import { PromptDetailPage } from './components/pages/tools/PromptDetailPage'
import { KeyMomentsLandingPage } from './components/pages/keyMoments/KeyMomentsLandingPage'
import { KeyMomentsAnalyzePage } from './components/pages/keyMoments/KeyMomentsAnalyzePage'
import { ChatPage } from './components/pages/chat/ChatPage'
import { SharedChatPage } from './components/pages/chat/SharedChatPage'
import { ThumbnailsLandingPage } from './components/pages/thumbnails/ThumbnailsLandingPage'
import { ThumbnailsWorkPage } from './components/pages/thumbnails/ThumbnailsWorkPage'
import { ReframeLandingPage } from './components/pages/reframe/ReframeLandingPage'
import { ReframeWorkPage } from './components/pages/reframe/ReframeWorkPage'
import { ReframeOutputPage } from './components/pages/reframe/ReframeOutputPage'
import { PromoLandingPage } from './components/pages/promo/PromoLandingPage'
import { PromoWorkPage } from './components/pages/promo/PromoWorkPage'
import { DubbingLandingPage } from './components/pages/dubbing/DubbingLandingPage'
import { DubbingWorkPage } from './components/pages/dubbing/DubbingWorkPage'
import { AdaptsLandingPage } from './components/pages/adapts/AdaptsLandingPage'
import { AdaptsWorkPage } from './components/pages/adapts/AdaptsWorkPage'
import { AdaptsOutputPage } from './components/pages/adapts/AdaptsOutputPage'
import { UploadsPage } from './components/pages/uploads/UploadsPage'
import { InviteCodesPage } from './components/pages/admin/InviteCodesPage'
import { ModelsPage } from './components/pages/admin/ModelsPage'
import { AvatarLandingPage } from './components/pages/avatar/AvatarLandingPage'
import { AvatarCreatePage } from './components/pages/avatar/AvatarCreatePage'
import { AvatarWorkPage } from './components/pages/avatar/AvatarWorkPage'
import { InviteCodeGate } from './components/InviteCodeGate'
import { ChatWidget } from './components/chat/ChatWidget'
import { PageTransition } from './components/shared/PageTransition'
import { ToastViewport } from './components/shared/ToastViewport'
import { useAuthStore } from './store/useAuthStore'
import { useChatStore } from './store/useChatStore'
import { api } from './lib/api'

const GUEST_INVITE_CODE = process.env.NEXT_PUBLIC_GUEST_INVITE_CODE || ''

function useGuestAndPersistedAuth() {
  const { isAuthenticated, inviteCode, login, logout } = useAuthStore()
  const [guestLoginPending, setGuestLoginPending] = useState(false)

  const tryGuestLogin = async () => {
    setGuestLoginPending(true)
    try {
      const result = await api.auth.validate(GUEST_INVITE_CODE)
      if (result.valid) login(GUEST_INVITE_CODE, result.is_master, result.is_power)
    } catch {
      // Fall back to the gate.
    } finally {
      setGuestLoginPending(false)
    }
  }

  useEffect(() => {
    if (isAuthenticated && inviteCode) {
      api.auth.validate(inviteCode).then((result) => {
        if (!result.valid) {
          logout()
          if (GUEST_INVITE_CODE) void tryGuestLogin()
        } else {
          login(inviteCode, result.is_master, result.is_power)
        }
      }).catch(() => {
        // Network error — don't logout, let subsequent API calls handle it.
      })
      return
    }
    if (GUEST_INVITE_CODE) void tryGuestLogin()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return guestLoginPending
}

function useHashAutoScroll(hash: string) {
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
}

const AppRoutes = ({ canWrite, isMaster }: { canWrite: boolean; isMaster: boolean }) => (
  <Routes>
    <Route path="/" element={<Navigate to={canWrite ? '/chat' : '/productions'} replace />} />
    <Route path="/chat" element={canWrite ? <ChatPage /> : <Navigate to="/productions" replace />} />
    <Route path="/productions" element={<ProjectList />} />
    <Route path="/productions/new" element={canWrite ? <ProjectForm /> : <Navigate to="/productions" replace />} />
    <Route path="/productions/:id" element={<ProductionSummary />} />
    <Route path="/productions/:id/edit" element={canWrite ? <ProjectForm /> : <Navigate to="/productions" replace />} />
    <Route path="/productions/:id/script" element={<RefinePromptView />} />
    <Route path="/key-moments" element={<KeyMomentsLandingPage />} />
    <Route path="/key-moments/analyze" element={canWrite ? <KeyMomentsAnalyzePage /> : <Navigate to="/key-moments" replace />} />
    <Route path="/key-moments/:id" element={<KeyMomentsAnalyzePage />} />
    <Route path="/thumbnails" element={<ThumbnailsLandingPage />} />
    <Route path="/thumbnails/create" element={canWrite ? <ThumbnailsWorkPage /> : <Navigate to="/thumbnails" replace />} />
    <Route path="/thumbnails/:id" element={<ThumbnailsWorkPage />} />
    <Route path="/orientations" element={<ReframeLandingPage />} />
    <Route path="/orientations/create" element={canWrite ? <ReframeWorkPage /> : <Navigate to="/orientations" replace />} />
    <Route path="/orientations/:id" element={<ReframeWorkPage />} />
    <Route path="/orientations/:id/:section" element={<ReframeOutputPage />} />
    <Route path="/promos" element={<PromoLandingPage />} />
    <Route path="/promos/create" element={canWrite ? <PromoWorkPage /> : <Navigate to="/promos" replace />} />
    <Route path="/promos/:id" element={<PromoWorkPage />} />
    <Route path="/avatars" element={canWrite ? <AvatarLandingPage /> : <Navigate to="/productions" replace />} />
    <Route path="/avatars/create" element={canWrite ? <AvatarCreatePage /> : <Navigate to="/productions" replace />} />
    <Route path="/avatars/:id" element={canWrite ? <AvatarWorkPage /> : <Navigate to="/productions" replace />} />
    <Route path="/dubbing" element={<DubbingLandingPage />} />
    <Route path="/dubbing/create" element={canWrite ? <DubbingWorkPage /> : <Navigate to="/dubbing" replace />} />
    <Route path="/dubbing/:id" element={<DubbingWorkPage />} />
    <Route path="/adapts" element={<AdaptsLandingPage />} />
    <Route path="/adapts/create" element={canWrite ? <AdaptsWorkPage /> : <Navigate to="/adapts" replace />} />
    <Route path="/adapts/:id" element={<AdaptsWorkPage />} />
    <Route path="/adapts/:id/prompt" element={<AdaptsOutputPage />} />
    <Route path="/adapts/:id/prompt/:variantIndex" element={<AdaptsOutputPage />} />
    <Route path="/uploads" element={<UploadsPage />} />
    <Route path="/uploads/:id" element={<UploadsPage />} />
    <Route path="/prompts" element={<PromptsPage />} />
    <Route path="/prompts/:id" element={<PromptDetailPage />} />
    {canWrite && (
      <>
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/diagnostics" element={<DiagnosticsPage />} />
      </>
    )}
    {isMaster && <Route path="/invite-codes" element={<InviteCodesPage />} />}
    <Route path="*" element={<Navigate to="/productions" replace />} />
  </Routes>
)

const MainAuthenticatedLayout = ({
  pathname,
  isFullscreen,
  canWrite,
  isMaster,
}: {
  pathname: string
  isFullscreen: boolean
  canWrite: boolean
  isMaster: boolean
}) => {
  const isChatFullscreen = pathname === '/chat' && isFullscreen
  const isFullWidthRoute = pathname.startsWith('/productions')
  const mainClass = isChatFullscreen
    ? 'flex-1 overflow-hidden p-0'
    : 'flex-1 overflow-x-hidden overflow-y-auto p-5 md:p-7'
  const innerClass = isChatFullscreen
    ? 'h-full w-full'
    : isFullWidthRoute
      ? 'w-full'
      : 'max-w-4xl mx-auto w-full'
  return (
    <div className="flex h-screen bg-background bg-accent-gradient">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <main className={mainClass}>
          <div className={innerClass}>
            <PageTransition>
              <AppRoutes canWrite={canWrite} isMaster={isMaster} />
            </PageTransition>
          </div>
        </main>
      </div>
      {canWrite && <ChatWidget />}
      <ToastViewport />
    </div>
  )
}

function App() {
  const { isAuthenticated, isMaster, isPower } = useAuthStore()
  const { isFullscreen } = useChatStore()
  const canWrite = isMaster || isPower
  const guestLoginPending = useGuestAndPersistedAuth()
  const { hash, pathname } = useLocation()
  useHashAutoScroll(hash)

  if (pathname.startsWith('/share/chat/')) {
    return (
      <>
        <Routes><Route path="/share/chat/:id" element={<SharedChatPage />} /></Routes>
        <ToastViewport />
      </>
    )
  }
  if (!isAuthenticated) {
    return GUEST_INVITE_CODE && guestLoginPending ? (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="w-6 h-6 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
      </div>
    ) : (
      <><InviteCodeGate /><ToastViewport /></>
    )
  }
  return <MainAuthenticatedLayout pathname={pathname} isFullscreen={isFullscreen} canWrite={canWrite} isMaster={isMaster} />
}

export default App
