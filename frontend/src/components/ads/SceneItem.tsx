import { useCallback, useRef, useState } from 'react'
import { PromptModal } from './PromptModal'
import { SceneItemGrid } from './studio/SceneItemGrid'
import { SceneItemList } from './studio/SceneItemList'
import { useAdsProjectActions } from './projects/useAdsProjectActions'
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

function extractFrameUpdates(data: Record<string, unknown> | string | undefined): Partial<Scene> {
  if (!data) return {}
  if (typeof data === 'string') return { thumbnail_url: data }
  const updates: Partial<Scene> = {}
  if (typeof data.image_url === 'string') updates.thumbnail_url = data.image_url
  if (typeof data.end_frame_url === 'string') updates.end_frame_url = data.end_frame_url
  if (typeof data.generated_prompt === 'string') {
    updates.image_prompt = data.generated_prompt
    updates.generated_prompt = data.generated_prompt
  }
  if (typeof data.end_frame_prompt === 'string') updates.end_frame_prompt = data.end_frame_prompt
  return updates
}

function useSceneFieldPersistence(
  productionId: string,
  sceneId: string,
  isReadOnly: boolean,
  onUpdate: (updates: Partial<Scene>) => void,
) {
  const { projects: projectsApi } = useAdsProjectActions()
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const persistScene = useCallback(
    (updates: Partial<Scene>) => {
      if (!productionId || !sceneId || isReadOnly) return
      projectsApi.updateScene(productionId, sceneId, updates).catch(() => {})
    },
    [projectsApi, productionId, sceneId, isReadOnly],
  )

  const handleToggle = (updates: Partial<Scene>) => {
    onUpdate(updates)
    persistScene(updates)
  }

  const handleTextChange = (updates: Partial<Scene>) => {
    onUpdate(updates)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => persistScene(updates), 800)
  }

  return { handleToggle, handleTextChange }
}

function useSceneMediaGeneration(
  productionId: string,
  sceneId: string,
  onUpdate: (updates: Partial<Scene>) => void,
) {
  const { projects: projectsApi } = useAdsProjectActions()
  const [isGeneratingFrame, setIsGeneratingFrame] = useState(false)
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const applyCompletedVideo = async (videoUrl?: string) => {
    const prod = await projectsApi.get(productionId)
    const updatedScene = prod?.scenes?.find((s: Scene) => s.id === sceneId)
    onUpdate({
      video_url: videoUrl,
      video_prompt: updatedScene?.video_prompt,
      generated_prompt: updatedScene?.generated_prompt,
    })
    setIsGeneratingVideo(false)
  }

  const pollVideoOperation = (opName: string) => {
    const poll = async () => {
      const status = await projectsApi.checkOperation(opName, productionId, sceneId)
      if (status.status === 'completed') {
        await applyCompletedVideo(status.signed_url || status.video_uri)
      } else if (status.status === 'failed' || status.status === 'error') {
        setError(status.message || 'Video generation failed')
        setIsGeneratingVideo(false)
      } else {
        setTimeout(poll, 10000)
      }
    }
    setTimeout(poll, 10000)
  }

  const handleGenerateFrame = async (promptData?: Record<string, unknown>) => {
    if (!productionId || !sceneId) return
    setIsGeneratingFrame(true)
    setError(null)
    try {
      const result = await projectsApi.generateFrame(productionId, sceneId, promptData)
      const updates = extractFrameUpdates(result.data)
      if (Object.keys(updates).length > 0) onUpdate(updates)
    } catch {
      setError('Frame generation failed')
    } finally {
      setIsGeneratingFrame(false)
    }
  }

  const handleGenerateVideo = async (promptData?: Record<string, unknown>) => {
    if (!productionId || !sceneId) return
    setIsGeneratingVideo(true)
    setError(null)
    try {
      const result = await projectsApi.generateSceneVideo(productionId, sceneId, promptData)
      if (result.status === 'completed' && result.signed_url) {
        await applyCompletedVideo(result.signed_url)
        return
      }
      if (result.operation_name) pollVideoOperation(result.operation_name)
    } catch {
      setError('Video generation failed')
      setIsGeneratingVideo(false)
    }
  }

  return { isGeneratingFrame, isGeneratingVideo, error, handleGenerateFrame, handleGenerateVideo }
}

export const SceneItem = ({ scene, index, layout, isReadOnly, productionId, orientation, onUpdate }: Props) => {
  const [showPromptModal, setShowPromptModal] = useState(false)
  const { handleToggle, handleTextChange } = useSceneFieldPersistence(productionId, scene.id, isReadOnly, onUpdate)
  const gen = useSceneMediaGeneration(productionId, scene.id, onUpdate)
  const activeFrame = gen.isGeneratingFrame || scene.status === 'generating_frame'
  const activeVideo = gen.isGeneratingVideo || scene.status === 'generating'
  const View = layout === 'grid' ? SceneItemGrid : SceneItemList
  const sceneErr = (scene as Scene & { error_message?: string }).error_message

  return (
    <>
      <View
        scene={scene} index={index} isReadOnly={isReadOnly} aspectClass={orientation === '9:16' ? 'aspect-[9/16]' : 'aspect-video'}
        isGeneratingFrame={activeFrame} isGeneratingVideo={activeVideo} isBusy={activeFrame || activeVideo}
        error={gen.error || sceneErr || null} handleToggle={handleToggle} handleTextChange={handleTextChange}
        handleGenerateFrame={() => gen.handleGenerateFrame()} handleGenerateVideo={() => gen.handleGenerateVideo()}
        onShowPromptModal={() => setShowPromptModal(true)}
      />
      {showPromptModal && (
        <PromptModal
          scene={scene} productionId={productionId} isReadOnly={isReadOnly} onClose={() => setShowPromptModal(false)}
          onGenerateFrame={gen.handleGenerateFrame} onGenerateVideo={gen.handleGenerateVideo}
          onDescriptionChange={(desc) => onUpdate({ visual_description: desc })}
        />
      )}
    </>
  )
}
