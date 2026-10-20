import type { ReactNode } from 'react'
import { StoryGraphVisualizer3D } from '@/components/ads/StoryGraphVisualizer3D'
import { Disclosure } from '@/components/ui/disclosure'
import {
  CANONICAL_PRODUCTION_DEFINITIONS,
  type StoryGraphData,
  type StoryGraphStageRun,
} from '@/types/project'
import type { ActiveStepId } from '../storyGraphStudioTypes'
import { AgentProgressChecklist } from '../AgentProgressChecklist'

export interface StudioAdvancedPanelProps {
  storyGraph?: StoryGraphData
  canWrite: boolean
  completedStages: Set<string>
  busyAction: string | null
  latestStageRunByStage: Record<string, StoryGraphStageRun>
  usage?: ReactNode
  onSelectStepGroup: (group: ActiveStepId) => void
  onAppearanceAction: (appearanceId: string, action: 'approve' | 'regenerate') => void
}

const Section = ({ title, hint, children, defaultOpen = false }: { title: string; hint?: string; children: ReactNode; defaultOpen?: boolean }) => (
  <Disclosure
    defaultOpen={defaultOpen}
    title={
      <div>
        <p className="text-sm font-medium text-foreground">{title}</p>
        {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      </div>
    }
    triggerClassName="px-5 py-4 hover:bg-muted/40"
    contentClassName="px-5 pb-5"
  >
    {children}
  </Disclosure>
)

const ConsistencyRules = () => (
  <div className="grid gap-4 md:grid-cols-3">
    {CANONICAL_PRODUCTION_DEFINITIONS.map((def) => (
      <div key={def.id} className="space-y-1">
        <p className="text-xs font-medium text-foreground">{def.title}</p>
        <p className="text-xs leading-relaxed text-muted-foreground">{def.summary}</p>
      </div>
    ))}
  </div>
)

/** Power-user surfaces kept out of the main flow: agent runs, usage, rules, and the 3D graph. */
export const StudioAdvancedPanel = (p: StudioAdvancedPanelProps) => (
  <div className="divide-y divide-border/60 overflow-hidden rounded-2xl bg-card/70 shadow-sm ring-1 ring-border/60">
    <Section title="Agent runs" hint="Per-agent status, retries and reviews across all 10 agents" defaultOpen>
      <AgentProgressChecklist
        completedStages={p.completedStages}
        busyAction={p.busyAction}
        latestStageRunByStage={p.latestStageRunByStage}
        qaReports={p.storyGraph?.stage_qa_reports || []}
        onSelectStepGroup={p.onSelectStepGroup}
      />
    </Section>
    {p.usage && (
      <Section title="Usage & cost" hint="Tokens, image generations and Veo seconds">
        {p.usage}
      </Section>
    )}
    <Section title="Consistency rules" hint="9.1–9.3 canonical production definitions">
      <ConsistencyRules />
    </Section>
    <Section title="3D knowledge graph" hint="Interactive view of every entity, scene and shot">
      <StoryGraphVisualizer3D
        storyGraph={p.storyGraph}
        canWrite={p.canWrite}
        onApproveAppearance={(id) => p.onAppearanceAction(id, 'approve')}
        onRegenerateAppearance={(id) => p.onAppearanceAction(id, 'regenerate')}
      />
    </Section>
  </div>
)
