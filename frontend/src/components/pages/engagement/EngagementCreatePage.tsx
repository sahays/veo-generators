import { useState } from 'react'
import { TrendingUp } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { ModelRegionPicker } from '@/components/ModelRegionPicker'
import { OptionalNameField, WorkCreateShell } from '@/components/shared/WorkPageShell'
import { api } from '@/hooks/useApiClient'
import { useCreateRecord, type CreateRecordOptions } from '@/hooks/useCreateRecord'
import { buildEngagementPayload, canStart } from '@/types/engagement/createForm'
import type { EngagementCreate } from '@/types/insights'
import { engagementCreateSchema } from '@/types/schemas'
import { FormStep } from './create/FormParts'
import { SignalStep } from './create/SignalStep'
import { useEngagementForm } from './create/useEngagementForm'
import { VideoStep } from './create/VideoStep'

const CREATE_OPTIONS: CreateRecordOptions<EngagementCreate> = {
  schema: engagementCreateSchema,
  send: (payload) => api.engagement.create(payload),
  detailPath: '/engagement',
  invalidMessage: 'Invalid engagement request',
  failureMessage: 'Could not start the engagement analysis',
}

/**
 * `/engagement/new` — pick a video (an analysed one is reused as is), choose
 * the engagement signal and start. `?analysis=<scene analysis id>` preselects
 * the video.
 */
export const EngagementCreatePage = () => {
  const [params] = useSearchParams()
  const form = useEngagementForm()
  const [modelConfig, setModelConfig] = useState<{ modelId?: string; region?: string }>({})
  const { submitting, error, submit } = useCreateRecord(CREATE_OPTIONS)

  return (
    <WorkCreateShell
      backPath="/engagement"
      backLabel="Back to Engagement"
      title="New Engagement Analysis"
      subtitle="Relate what happens in a video to an engagement curve"
      error={error}
      actionIcon={TrendingUp}
      actionLabel="Start Analysis"
      submitting={submitting}
      disabled={!canStart(form.state)}
      onSubmit={() => submit(buildEngagementPayload(form.state, modelConfig))}
      actionLeft={<ModelRegionPicker capability="text" value={modelConfig} onChange={setModelConfig} />}
    >
      <FormStep number={1} title="Video">
        <VideoStep form={form} preselectId={params.get('analysis')} />
      </FormStep>
      <FormStep number={2} title="Engagement signal">
        <SignalStep form={form} />
      </FormStep>
      <OptionalNameField value={form.state.name} onChange={form.setName} placeholder="Defaults to the video's file name" />
    </WorkCreateShell>
  )
}
