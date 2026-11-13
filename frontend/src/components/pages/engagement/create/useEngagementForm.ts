import { useEffect, useState } from 'react'
import { useVideoSourcePicker, type PickedVideoSource, type VideoSourcePickerState } from '@/components/shared/media/VideoSourcePicker'
import { api } from '@/hooks/useApiClient'
import {
  EMPTY_BARC,
  type BarcSelection,
  type EngagementFormState,
  type VideoChoice,
} from '@/types/engagement/createForm'

export interface EngagementForm {
  state: EngagementFormState
  /** The "Other videos" picker (uploads and productions). */
  picker: VideoSourcePickerState
  pickAnalysis: (choice: VideoChoice | null) => void
  setSignalChoice: (choice: string) => void
  setBarc: (barc: BarcSelection) => void
  setName: (name: string) => void
}

function sourceChoice(source: PickedVideoSource): VideoChoice {
  return { kind: 'source', sourceType: source.source_type, sourceId: source.source_id, name: source.name, videoUrl: source.video_url }
}

/**
 * State of the create form. The video is either an analysed video or one
 * picked under "Other videos"; choosing on one side clears the other.
 */
export function useEngagementForm(): EngagementForm {
  const picker = useVideoSourcePicker({
    loadUploads: () => api.engagement.listUploadSources(),
    loadProductions: () => api.engagement.listProductionSources(),
  })
  const [analysis, setAnalysis] = useState<VideoChoice | null>(null)
  const [signalChoice, setSignalChoice] = useState('')
  const [barc, setBarc] = useState<BarcSelection>(EMPTY_BARC)
  const [name, setName] = useState('')
  const picked = picker.value

  useEffect(() => {
    if (picked) setAnalysis(null)
  }, [picked])

  const pickAnalysis = (choice: VideoChoice | null): void => {
    picker.select(null)
    setAnalysis(choice)
  }
  const video = picked ? sourceChoice(picked) : analysis
  return { state: { video, signalChoice, barc, name }, picker, pickAnalysis, setSignalChoice, setBarc, setName }
}
