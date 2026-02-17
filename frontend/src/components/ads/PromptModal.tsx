import { useState, useEffect } from 'react'
import { ImageIcon, Video, Loader2 } from 'lucide-react'
import { Modal } from '@/components/Modal'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import type { Scene } from '@/types/project'

interface PromptModalProps {
  scene: Scene
  productionId: string
  isReadOnly?: boolean
  onClose: () => void
  onGenerateFrame: (promptData: any) => Promise<void>
  onGenerateVideo: (promptData: any) => Promise<void>
  onDescriptionChange: (newDescription: string) => void
}

export const PromptModal = ({
  scene,
  productionId,
  isReadOnly,
  onClose,
  onGenerateFrame,
  onGenerateVideo,
  onDescriptionChange,
}: PromptModalProps) => {
  const [promptJson, setPromptJson] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isGeneratingFrame, setIsGeneratingFrame] = useState(false)
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [originalDescription, setOriginalDescription] = useState('')

  useEffect(() => {
    setIsLoading(true)
    api.projects.buildPrompt(productionId, scene.id)
      .then((data) => {
        setPromptJson(JSON.stringify(data, null, 2))
        setOriginalDescription(data.visual_description || '')
        setIsLoading(false)
      })
      .catch(() => {
        setError('Failed to load prompt data')
        setIsLoading(false)
      })
  }, [productionId, scene.id])

  const getParsedData = () => {
    try {
      return JSON.parse(promptJson)
    } catch {
      setError('Invalid JSON')
      return null
    }
  }

  const syncDescription = (data: any) => {
    if (data.visual_description && data.visual_description !== originalDescription) {
      onDescriptionChange(data.visual_description)
    }
  }

  const handleGenerateFrame = async () => {
    const data = getParsedData()
    if (!data) return
    setError(null)
    setIsGeneratingFrame(true)
    syncDescription(data)
    try {
      await onGenerateFrame(data)
      onClose()
    } catch {
      setError('Frame generation failed')
    } finally {
      setIsGeneratingFrame(false)
    }
  }

  const handleGenerateVideo = async () => {
    const data = getParsedData()
    if (!data) return
    setError(null)
    setIsGeneratingVideo(true)
    syncDescription(data)
    try {
      await onGenerateVideo(data)
      onClose()
    } catch {
      setError('Video generation failed')
    } finally {
      setIsGeneratingVideo(false)
    }
  }

  const isBusy = isGeneratingFrame || isGeneratingVideo

  return (
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
              onClick={handleGenerateFrame}
              disabled={isBusy || isLoading}
            >
              {isGeneratingFrame ? 'Generating...' : 'Generate Frame'}
            </Button>
            <Button
              icon={isGeneratingVideo ? Loader2 : Video}
              onClick={handleGenerateVideo}
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
          <textarea
            value={promptJson}
            onChange={(e) => { setPromptJson(e.target.value); setError(null) }}
            readOnly={isReadOnly}
            className="w-full min-h-[400px] p-4 rounded-xl text-xs font-mono leading-relaxed bg-muted/30 border border-border focus:ring-2 focus:ring-accent/30 outline-none resize-y"
            spellCheck={false}
          />
        </div>
      )}
    </Modal>
  )
}
