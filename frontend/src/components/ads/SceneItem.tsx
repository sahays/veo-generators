import { useCallback, useRef, useState } from 'react'
import { PromptModal } from '@/components/ads/PromptModal'
import { SceneItemGrid } from '@/components/ads/SceneItemGrid'
import { SceneItemList } from '@/components/ads/SceneItemList'
import { api } from '@/lib/api'
import type { Scene } from '@/types/project'

interface Props {
  scene: Scene
  index: number
  layout: 'grid' | 'list'
  isReadOnly: boolean
  productionId: string
  orientation: string
  onUpdate: (updates: Partial<Scene>) => void
}

export const SceneItem = ({
  scene,
  index,
  layout,
  isReadOnly,
  productionId,
  orientation,
  onUpdate,
}: Props) => {
  const isPortrait = orientation === '9:16'
  const aspectClass = isPortrait ? 'aspect-[9/16]' : 'aspect-video'
  const [isGeneratingFrame, setIsGeneratingFrame] = useState(false)
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showPromptModal, setShowPromptModal] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const persistScene = useCallback((updates: Partial<Scene>) => {
    if (!productionId || !scene.id || isReadOnly) return
    api.projects.updateScene(productionId, scene.id, updates).catch(() => {})
  }, [productionId, scene.id, isReadOnly])

  const handleToggle = (updates: Partial<Scene>) => {
    onUpdate(updates)
    persistScene(updates)
  }

  const handleTextChange = (updates: Partial<Scene>) => {
    onUpdate(updates)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => persistScene(updates), 800)
  }

  const handleGenerateFrame = async (promptData?: any) => {
    if (!productionId || !scene.id) return
    setIsGeneratingFrame(true)
    setError(null)
    try {
      const result = await api.projects.generateFrame(productionId, scene.id, promptData)
      const imageUrl = result.data?.image_url || result.data
      const updates: Partial<Scene> = {}
      if (imageUrl && typeof imageUrl === 'string') updates.thumbnail_url = imageUrl
      if (result.data?.generated_prompt) {
        updates.image_prompt = result.data.generated_prompt
        updates.generated_prompt = result.data.generated_prompt
      }
      if (Object.keys(updates).length > 0) onUpdate(updates)
    } catch (err) {
      console.error('Frame generation failed:', err)
      setError('Frame generation failed')
    } finally {
      setIsGeneratingFrame(false)
    }
  }

  const handleGenerateVideo = async (promptData?: any) => {
    if (!productionId || !scene.id) return
    setIsGeneratingVideo(true)
    setError(null)
    try {
      const result = await api.projects.generateSceneVideo(productionId, scene.id, promptData)
      if (result.status === 'completed' && result.signed_url) {
        const prod = await api.projects.get(productionId)
        const updatedScene = prod?.scenes?.find((s: Scene) => s.id === scene.id)
        onUpdate({
          video_url: result.signed_url,
          video_prompt: updatedScene?.video_prompt,
          generated_prompt: updatedScene?.generated_prompt,
        })
        setIsGeneratingVideo(false)
        return
      }
      if (result.operation_name) {
        const poll = async () => {
          const status = await api.projects.checkOperation(
            result.operation_name, productionId, scene.id,
          )
          if (status.status === 'completed') {
            const prod = await api.projects.get(productionId)
            const updatedScene = prod?.scenes?.find((s: Scene) => s.id === scene.id)
            onUpdate({
              video_url: status.signed_url || status.video_uri,
              video_prompt: updatedScene?.video_prompt,
              generated_prompt: updatedScene?.generated_prompt,
            })
            setIsGeneratingVideo(false)
          } else if (status.status === 'failed' || status.status === 'error') {
            setError(status.message || 'Video generation failed')
            setIsGeneratingVideo(false)
          } else {
            setTimeout(poll, 10000)
          }
        }
        setTimeout(poll, 10000)
      }
    } catch (err) {
      console.error('Video generation failed:', err)
      setError('Video generation failed')
      setIsGeneratingVideo(false)
    }
  }

  const isBusy = isGeneratingFrame || isGeneratingVideo
  const View = layout === 'grid' ? SceneItemGrid : SceneItemList

  return (
    <>
      <View
        scene={scene}
        index={index}
        isReadOnly={isReadOnly}
        aspectClass={aspectClass}
        isGeneratingFrame={isGeneratingFrame}
        isGeneratingVideo={isGeneratingVideo}
        isBusy={isBusy}
        error={error}
        handleToggle={handleToggle}
        handleTextChange={handleTextChange}
        handleGenerateFrame={() => handleGenerateFrame()}
        handleGenerateVideo={() => handleGenerateVideo()}
        onShowPromptModal={() => setShowPromptModal(true)}
      />
      {showPromptModal && (
        <PromptModal
          scene={scene}
          productionId={productionId}
          isReadOnly={isReadOnly}
          onClose={() => setShowPromptModal(false)}
          onGenerateFrame={handleGenerateFrame}
          onGenerateVideo={handleGenerateVideo}
          onDescriptionChange={(desc) => onUpdate({ visual_description: desc })}
        />
      )}
    </>
  )
}
