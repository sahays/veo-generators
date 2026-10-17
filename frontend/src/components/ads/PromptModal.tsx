import { useState, useEffect } from 'react'
import { ImageIcon, Video, Loader2 } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/Common'
import { Textarea } from '@/components/ui/textarea'
import { useAdsProjectActions } from './projects/useAdsProjectActions'
import type { Scene } from '@/types/project'

interface PromptModalProps {
  scene: Scene
  productionId: string
  isReadOnly?: boolean
  onClose: () => void
  onGenerateFrame: (promptData: Record<string, unknown>) => Promise<void>
  onGenerateVideo: (promptData: Record<string, unknown>) => Promise<void>
  onDescriptionChange: (newDescription: string) => void
}

const PromptModalView = ({
  isReadOnly,
  isBusy,
  isLoading,
  isGeneratingFrame,
  isGeneratingVideo,
  error,
  promptJson,
  onClose,
  onGenerateFrame,
  onGenerateVideo,
  onChangeJson,
}: {
  isReadOnly?: boolean
  isBusy: boolean
  isLoading: boolean
  isGeneratingFrame: boolean
  isGeneratingVideo: boolean
  error: string | null
  promptJson: string
  onClose: () => void
  onGenerateFrame: () => void
  onGenerateVideo: () => void
  onChangeJson: (val: string) => void
}) => (
  <Modal
    isOpen={true}
    onClose={onClose}
    title="Edit Scene Prompt"
    subtitle="Full enriched prompt with all production context. Edit and regenerate."
    maxWidth="max-w-2xl"
    footer={
      !isReadOnly ? (
        <>
          <Button
            variant="secondary"
            icon={isGeneratingFrame ? Loader2 : ImageIcon}
            onClick={onGenerateFrame}
            disabled={isBusy || isLoading}
          >
            {isGeneratingFrame ? 'Generating...' : 'Generate Frame'}
          </Button>
          <Button
            icon={isGeneratingVideo ? Loader2 : Video}
            onClick={onGenerateVideo}
            disabled={isBusy || isLoading}
          >
            {isGeneratingVideo ? 'Generating...' : 'Generate Video'}
          </Button>
        </>
      ) : undefined
    }
  >
    {isLoading ? (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="animate-spin text-accent" size={24} />
      </div>
    ) : (
      <div className="space-y-3">
        {error && <p className="text-xs text-red-500">{error}</p>}
        <Textarea
          value={promptJson}
          onChange={(e) => onChangeJson(e.target.value)}
          readOnly={isReadOnly}
          className="w-full min-h-[400px] p-4 rounded-xl text-xs font-mono leading-relaxed bg-muted/30 border border-border resize-y"
          spellCheck={false}
        />
      </div>
    )}
  </Modal>
)

function usePromptLoader(productionId: string, sceneId: string) {
  const { projects: projectsApi } = useAdsProjectActions()
  const [promptJson, setPromptJson] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [originalDescription, setOriginalDescription] = useState('')

  useEffect(() => {
    setIsLoading(true)
    projectsApi
      .buildPrompt(productionId, sceneId)
      .then((data) => {
        setPromptJson(JSON.stringify(data, null, 2))
        setOriginalDescription(data.visual_description || '')
        setIsLoading(false)
      })
      .catch(() => {
        setError('Failed to load prompt data')
        setIsLoading(false)
      })
  }, [projectsApi, productionId, sceneId])

  return { promptJson, setPromptJson, isLoading, error, setError, originalDescription }
}

function parsePromptJson(raw: string, setError: (msg: string | null) => void): Record<string, unknown> | null {
  try {
    return JSON.parse(raw) as Record<string, unknown>
  } catch {
    setError('Invalid JSON')
    return null
  }
}

export const PromptModal = ({
  scene, productionId, isReadOnly, onClose, onGenerateFrame, onGenerateVideo, onDescriptionChange,
}: PromptModalProps) => {
  const { promptJson, setPromptJson, isLoading, error, setError, originalDescription } = usePromptLoader(productionId, scene.id)
  const [isGeneratingFrame, setIsGeneratingFrame] = useState(false)
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false)

  const runAction = async (action: (data: Record<string, unknown>) => Promise<void>, setBusy: (v: boolean) => void, errMsg: string) => {
    const data = parsePromptJson(promptJson, setError)
    if (!data) return
    setError(null)
    setBusy(true)
    const desc = typeof data.visual_description === 'string' ? data.visual_description : ''
    if (desc && desc !== originalDescription) onDescriptionChange(desc)
    try { await action(data); onClose() } catch { setError(errMsg) } finally { setBusy(false) }
  }

  return (
    <PromptModalView
      isReadOnly={isReadOnly} isBusy={isGeneratingFrame || isGeneratingVideo} isLoading={isLoading}
      isGeneratingFrame={isGeneratingFrame} isGeneratingVideo={isGeneratingVideo} error={error} promptJson={promptJson}
      onClose={onClose} onGenerateFrame={() => runAction(onGenerateFrame, setIsGeneratingFrame, 'Frame generation failed')}
      onGenerateVideo={() => runAction(onGenerateVideo, setIsGeneratingVideo, 'Video generation failed')}
      onChangeJson={(val) => { setPromptJson(val); setError(null) }}
    />
  )
}
