import { useId, useState } from 'react'
import { ScanSearch } from 'lucide-react'
import { Textarea } from '@/components/Common'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { api } from '@/hooks/useApiClient'
import { useCreateRecord, type CreateRecordOptions } from '@/hooks/useCreateRecord'
import { sceneAnalysisCreateSchema } from '@/types/schemas'
import { OptionalNameField, SelectedVideoPreview, WorkCreateShell } from '@/components/shared/WorkPageShell'
import {
  VideoSourcePicker,
  useVideoSourcePicker,
  type PickedVideoSource,
} from '@/components/shared/media/VideoSourcePicker'
import type { SceneAnalysisCreate } from '@/types/insights'

const FOCUS_MAX_LENGTH = 500
const LABEL_CLASS = 'block text-sm font-medium text-foreground'

const CREATE_OPTIONS: CreateRecordOptions<SceneAnalysisCreate> = {
  schema: sceneAnalysisCreateSchema,
  send: (payload) => api.sceneAnalysis.create(payload),
  detailPath: '/scene-analysis',
  invalidMessage: 'Invalid scene analysis request',
  failureMessage: 'Could not start the scene analysis',
}

interface ModelConfig {
  modelId?: string
  region?: string
}

interface AnalysisOptions {
  focus: string
  name: string
}

function buildCreatePayload(
  source: PickedVideoSource | null,
  options: AnalysisOptions,
  modelConfig: ModelConfig,
): SceneAnalysisCreate {
  return {
    source_type: source?.source_type ?? 'upload',
    source_id: source?.source_id ?? '',
    focus: options.focus.trim() || undefined,
    display_name: options.name.trim() || undefined,
    model_id: modelConfig.modelId,
    region: modelConfig.region,
  }
}

const FocusField = ({ value, onChange }: { value: string; onChange: (value: string) => void }) => {
  const id = useId()
  const helpId = `${id}-help`
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className={LABEL_CLASS}>Focus (optional)</label>
      <Textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={FOCUS_MAX_LENGTH}
        rows={3}
        placeholder="e.g. product shots and brand mentions"
        aria-describedby={helpId}
      />
      <div className="flex items-start justify-between gap-3 text-xs text-muted-foreground">
        <p id={helpId}>
          Steers what the analysis pays attention to, for example &ldquo;product shots and brand mentions&rdquo;. Leave empty for a general breakdown.
        </p>
        <span className="shrink-0 tabular-nums">{value.length}/{FOCUS_MAX_LENGTH}</span>
      </div>
    </div>
  )
}

export const SceneAnalysisCreatePage = () => {
  const picker = useVideoSourcePicker({
    loadUploads: () => api.sceneAnalysis.listUploadSources(),
    loadProductions: () => api.sceneAnalysis.listProductionSources(),
  })
  const [options, setOptions] = useState<AnalysisOptions>({ focus: '', name: '' })
  const [modelConfig, setModelConfig] = useState<ModelConfig>({})
  const { submitting, error, submit } = useCreateRecord(CREATE_OPTIONS)

  return (
    <WorkCreateShell
      backPath="/scene-analysis"
      backLabel="Back to Scene Analysis"
      title="New Scene Analysis"
      subtitle="Pick a video to break down into scenes, dialogue, entities, emotions and key moments"
      error={error}
      actionIcon={ScanSearch}
      actionLabel="Start Analysis"
      submitting={submitting}
      disabled={!picker.value}
      onSubmit={() => submit(buildCreatePayload(picker.value, options, modelConfig))}
      actionLeft={<ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} />}
    >
      <VideoSourcePicker picker={picker} />
      <SelectedVideoPreview videoUrl={picker.value?.video_url ?? null} videoFilename={picker.value?.name} />
      <FocusField value={options.focus} onChange={(focus) => setOptions((prev) => ({ ...prev, focus }))} />
      <OptionalNameField value={options.name} onChange={(name) => setOptions((prev) => ({ ...prev, name }))} placeholder="Defaults to the title found in the video" />
    </WorkCreateShell>
  )
}
