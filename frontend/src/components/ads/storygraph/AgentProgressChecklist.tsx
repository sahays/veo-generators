import { motion } from 'framer-motion'
import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Checkbox } from '@/components/ui/checkbox'
import type { StoryGraphStageQaReport, StoryGraphStageRun } from '@/types/project'
import { PIPELINE_SUB_STAGES, type ActiveStepId } from './storyGraphStudioTypes'

const AgentChecklistItem = ({
  sub,
  index,
  isDone,
  isRunning,
  isFailed,
  stageRun,
  reviewCount,
  onSelect,
}: {
  sub: (typeof PIPELINE_SUB_STAGES)[number]
  index: number
  isDone: boolean
  isRunning: boolean
  isFailed: boolean
  stageRun?: StoryGraphStageRun
  reviewCount: number
  onSelect: () => void
}) => (
  <motion.div
    layout
    initial={{ opacity: 0, y: 6 }}
    animate={{
      opacity: 1,
      y: 0,
      scale: isDone ? [1, 1.025, 1] : isRunning ? 1.01 : 1,
    }}
    transition={{ duration: 0.35, delay: index * 0.02, type: 'spring', stiffness: 360, damping: 24 }}
    onClick={onSelect}
    className={cn(
      'cursor-pointer rounded-xl border px-3 py-2.5 flex items-center justify-between gap-2.5 transition-all',
      isFailed
        ? 'bg-red-500/15 border-red-500/50'
        : isRunning
          ? 'bg-accent/15 border-accent ring-1 ring-accent/50 shadow-[0_0_20px_rgba(56,189,248,0.2)]'
          : isDone
            ? 'bg-emerald-500/10 border-emerald-500/35 shadow-[0_0_14px_rgba(16,185,129,0.12)] hover:border-emerald-500/60'
            : 'bg-muted/25 border-border/60 opacity-75 hover:opacity-100',
    )}
  >
    <div className="flex items-center gap-2.5 min-w-0">
      <Checkbox
        checked={isDone}
        loading={isRunning}
        aria-label={`${sub.label} completion status`}
      />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-mono font-bold text-accent-dark">{sub.short}</span>
          <span
            className={cn(
              'text-xs font-semibold truncate transition-colors',
              isDone ? 'text-emerald-300' : isRunning ? 'text-foreground' : 'text-muted-foreground',
            )}
          >
            {sub.label}
          </span>
        </div>
        <p className="text-[10px] font-mono text-muted-foreground truncate">{sub.role}</p>
      </div>
    </div>
    <div className="flex items-center gap-1.5 shrink-0">
      {reviewCount > 1 && (
        <span className="px-1.5 py-0.5 rounded bg-accent/15 text-accent-dark border border-accent/30 text-[9px] font-mono font-bold">
          {reviewCount}× Review
        </span>
      )}
      {isDone && (
        <motion.span
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 450, damping: 18 }}
          className="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[9px] font-mono font-bold"
        >
          {stageRun?.duration_s ? `${stageRun.duration_s.toFixed(1)}s` : 'Done'} ✓
        </motion.span>
      )}
      {isRunning && (
        <span className="px-1.5 py-0.5 rounded bg-accent/20 text-accent-dark text-[9px] font-mono font-bold animate-pulse">
          Active...
        </span>
      )}
    </div>
  </motion.div>
)

export const AgentProgressChecklist = ({
  completedStages,
  busyAction,
  latestStageRunByStage,
  qaReports,
  onSelectStepGroup,
}: {
  completedStages: Set<string>
  busyAction: string | null
  latestStageRunByStage: Record<string, StoryGraphStageRun>
  qaReports: StoryGraphStageQaReport[]
  onSelectStepGroup: (group: ActiveStepId) => void
}) => {
  const doneCount = PIPELINE_SUB_STAGES.filter((s) => completedStages.has(s.id)).length
  const pct = Math.round((doneCount / PIPELINE_SUB_STAGES.length) * 100)
  return (
    <div className="rounded-xl border border-border/70 bg-card/60 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-emerald-400" />
          <span className="text-xs font-heading font-bold uppercase tracking-wider text-foreground">
            Autonomous Agent Checklist (Iterative 3× Review &amp; Physics QA)
          </span>
        </div>
        <span className="text-[11px] font-mono font-bold text-emerald-400">
          {doneCount}/{PIPELINE_SUB_STAGES.length} Agents Checked Off ({pct}%)
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
        <motion.div
          className="h-full bg-gradient-to-r from-accent via-emerald-400 to-emerald-500"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ type: 'spring', stiffness: 120, damping: 20 }}
        />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-2.5">
        {PIPELINE_SUB_STAGES.map((sub, idx) => {
          const sr = latestStageRunByStage[sub.id]
          const revs = qaReports.filter((r) => r.stage === sub.id).length
          return (
            <AgentChecklistItem
              key={sub.id}
              sub={sub}
              index={idx}
              isDone={completedStages.has(sub.id)}
              isRunning={busyAction === sub.id}
              isFailed={sr?.status === 'failed' || !!sr?.error}
              stageRun={sr}
              reviewCount={revs}
              onSelect={() => onSelectStepGroup(sub.stepGroup)}
            />
          )
        })}
      </div>
    </div>
  )
}
