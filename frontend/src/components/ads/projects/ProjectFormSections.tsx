import type { UseFormRegister, UseFormSetValue, FieldErrors } from 'react-hook-form'
import {
  FileText,
  Monitor,
  Smartphone,
  Clock,
  Clapperboard,
  Megaphone,
  Share2,
  Globe,
  CheckSquare,
  Square,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  type ProjectFormData,
  MODE_FORMAT_PROFILES,
  PRODUCTION_LANGUAGES,
} from '@/types/project'

const FORMAT_OPTIONS: Array<{
  id: ProjectFormData['type']
  label: string
  icon: typeof Clapperboard
  desc: string
}> = [
  { id: 'movie', label: 'Cinematic Film', icon: Clapperboard, desc: 'Widescreen long-form cinema (1m to 3m+)' },
  { id: 'advertizement', label: 'Commercial / Ad', icon: Megaphone, desc: 'High-impact spot (up to 30s)' },
  { id: 'social', label: 'Social Video / Reel', icon: Share2, desc: 'Tall or wide creator story (30s to 1m+)' },
]

const ORIENTATION_OPTIONS: Array<{
  id: ProjectFormData['orientation']
  label: string
  icon: typeof Monitor
}> = [
  { id: '16:9', label: '16:9 Widescreen', icon: Monitor },
  { id: '9:16', label: '9:16 Tall / Vertical', icon: Smartphone },
]

export const ProductionFormatCard = ({
  projectType,
  setValue,
}: {
  projectType: ProjectFormData['type']
  setValue: UseFormSetValue<ProjectFormData>
}) => (
  <Card
    title="Production Format Mode"
    icon={projectType === 'movie' ? Clapperboard : projectType === 'social' ? Share2 : Megaphone}
  >
    <div className="flex flex-wrap gap-4">
      {FORMAT_OPTIONS.map((opt) => {
        const profile = MODE_FORMAT_PROFILES[opt.id]
        return (
          <Button
            variant="unstyled"
            key={opt.id}
            type="button"
            onClick={() => {
              setValue('type', opt.id)
              setValue('orientation', profile.defaultOrientation)
              setValue('video_length', 'auto')
            }}
            className={cn(
              'flex-1 flex items-center gap-3 p-3 rounded-[6px] border transition-all text-left',
              projectType === opt.id
                ? 'bg-accent/10 border-accent text-accent-dark shadow-sm'
                : 'border-border text-muted-foreground hover:border-accent/30',
            )}
          >
            <div
              className={cn(
                'p-2 rounded-[5px]',
                projectType === opt.id ? 'btn-primary text-white' : 'bg-muted',
              )}
            >
              <opt.icon size={18} />
            </div>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-wider">{opt.label}</p>
              <p className="text-[10px] opacity-70">{opt.desc}</p>
            </div>
          </Button>
        )
      })}
    </div>
  </Card>
)

export const StoryConceptCard = ({
  register,
  errors,
  conceptLength,
}: {
  register: UseFormRegister<ProjectFormData>
  errors: FieldErrors<ProjectFormData>
  conceptLength: number
}) => (
  <Card title="Story Concept & Narrative Brief" icon={FileText}>
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Production Title
        </label>
        <Input
          {...register('name')}
          placeholder="e.g. Midnight Signal at Victoria Terminus"
          className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border"
        />
        {errors.name && <p className="text-[10px] text-red-500">{errors.name.message}</p>}
      </div>

      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Story Idea or Full Script
          </label>
          <span className="text-[10px] font-mono text-muted-foreground">
            {conceptLength}/10000
          </span>
        </div>
        <Textarea
          {...register('base_concept')}
          rows={6}
          placeholder="Describe characters, locations, props, key events, or paste a multi-scene story..."
          className="w-full px-3 py-2 rounded-lg text-sm glass bg-card border border-border resize-none"
        />
        {errors.base_concept && (
          <p className="text-[10px] text-red-500">{errors.base_concept.message}</p>
        )}
      </div>
    </div>
  </Card>
)

const IndicativeDurationCard = ({
  profile,
  videoLength,
  setValue,
}: {
  profile: (typeof MODE_FORMAT_PROFILES)[keyof typeof MODE_FORMAT_PROFILES]
  videoLength: ProjectFormData['video_length']
  setValue: UseFormSetValue<ProjectFormData>
}) => {
  const isAuto = videoLength === 'auto'
  return (
    <Card title="Target Duration (Indicative)" icon={Clock}>
      <div className="space-y-2.5">
        <div className="flex items-center justify-between gap-2 pb-1 border-b border-border/50">
          <Button
            variant="unstyled"
            type="button"
            onClick={() => setValue('video_length', isAuto ? profile.defaultDuration : 'auto')}
            className={cn(
              'inline-flex items-center gap-2 px-2.5 py-1.5 rounded-[5px] border text-xs font-bold transition-all',
              isAuto
                ? 'bg-accent/10 border-accent text-accent-dark shadow-sm'
                : 'border-border text-muted-foreground hover:border-accent/40',
            )}
          >
            {isAuto ? <CheckSquare size={14} className="text-accent-dark" /> : <Square size={14} />}
            <span>Auto (Let Story Content Decide Length)</span>
          </Button>
          <span className="text-[10px] font-mono text-muted-foreground">
            {isAuto ? 'Auto-Paced' : `${videoLength}s Target`}
          </span>
        </div>
        <div className="flex flex-wrap gap-2.5">
          {profile.indicativeDurations.map((opt) => (
            <Button
              key={opt.value}
              variant="unstyled"
              type="button"
              onClick={() => setValue('video_length', opt.value)}
              className={cn(
                'flex-1 min-w-[90px] px-3 py-2 rounded-[5px] border text-left transition-all',
                videoLength === opt.value
                  ? 'btn-primary text-white border-transparent'
                  : 'border-border hover:border-accent/50 text-muted-foreground',
              )}
            >
              <div className="text-xs font-bold">{opt.label}</div>
              <div className="text-[9px] opacity-80">{opt.tag}</div>
            </Button>
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground leading-snug">{profile.durationNote}</p>
      </div>
    </Card>
  )
}

const AspectRatioCard = ({
  profile,
  orientation,
  setValue,
}: {
  profile: (typeof MODE_FORMAT_PROFILES)[keyof typeof MODE_FORMAT_PROFILES]
  orientation: ProjectFormData['orientation']
  setValue: UseFormSetValue<ProjectFormData>
}) => (
  <Card title="Aspect Ratio" icon={orientation === '16:9' ? Monitor : Smartphone}>
    <div className="space-y-2.5">
      <div className="flex gap-4">
        {ORIENTATION_OPTIONS.map((opt) => {
          const isAllowed = profile.allowedOrientations.includes(opt.id)
          return (
            <Button
              variant="unstyled"
              key={opt.id}
              type="button"
              disabled={!isAllowed}
              onClick={() => isAllowed && setValue('orientation', opt.id)}
              className={cn(
                'flex-1 flex flex-col items-center gap-2 p-3 rounded-[6px] border transition-all',
                orientation === opt.id
                  ? 'bg-accent/10 border-accent text-accent-dark'
                  : isAllowed
                    ? 'border-border text-muted-foreground hover:border-accent/30'
                    : 'border-border/40 text-muted-foreground/40 cursor-not-allowed',
              )}
            >
              <opt.icon size={20} />
              <span className="text-[10px] font-bold uppercase tracking-widest">{opt.label}</span>
            </Button>
          )
        })}
      </div>
      <p className="text-[10px] text-muted-foreground">
        {profile.type === 'movie'
          ? 'Cinematic mode enforces widescreen 16:9 framing.'
          : 'Choose widescreen 16:9 or vertical 9:16 framing.'}
      </p>
    </div>
  </Card>
)

export const DurationAndAspectGrid = ({
  projectType,
  videoLength,
  orientation,
  setValue,
}: {
  projectType?: ProjectFormData['type']
  videoLength: ProjectFormData['video_length']
  orientation: ProjectFormData['orientation']
  setValue: UseFormSetValue<ProjectFormData>
}) => {
  const profile = MODE_FORMAT_PROFILES[projectType || 'movie'] || MODE_FORMAT_PROFILES.movie
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
      <IndicativeDurationCard profile={profile} videoLength={videoLength} setValue={setValue} />
      <AspectRatioCard profile={profile} orientation={orientation} setValue={setValue} />
    </div>
  )
}

export const LanguageAndGateModeCard = ({
  language,
  autoApproveGates,
  setValue,
}: {
  language: ProjectFormData['language']
  autoApproveGates: boolean
  setValue: UseFormSetValue<ProjectFormData>
}) => (
  <Card title="Spoken Language & Studio Gate Mode" icon={Globe}>
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {PRODUCTION_LANGUAGES.map((langOpt) => (
          <Button
            variant="unstyled"
            key={langOpt.id}
            type="button"
            onClick={() => setValue('language', langOpt.id)}
            className={cn(
              'flex flex-col items-start gap-1 p-3 rounded-[6px] border transition-all text-left',
              language === langOpt.id
                ? 'bg-accent/10 border-accent text-accent-dark shadow-sm'
                : 'border-border text-muted-foreground hover:border-accent/30',
            )}
          >
            <span className="text-xs font-bold">{langOpt.label}</span>
            <span className="text-[10px] opacity-75">{langOpt.sub}</span>
          </Button>
        ))}
      </div>
      <div className="pt-3 border-t border-border/50 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-bold text-foreground">Human-in-the-Loop Gate Mode</p>
          <p className="text-[10px] text-muted-foreground">
            Pause for review at Gate G1 (Entities), Gate G2 (Reference Sheets), and Gate G3 (Shots & Prompts), or auto-approve all gates.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {[
            { val: false, label: 'Interactive Gates (G1 · G2 · G3)' },
            { val: true, label: 'Auto-Approve Gates' },
          ].map((opt) => (
            <Button
              key={String(opt.val)}
              type="button"
              size="xs"
              variant={autoApproveGates === opt.val ? 'primary' : 'outline'}
              onClick={() => setValue('auto_approve_gates', opt.val)}
            >
              {opt.label}
            </Button>
          ))}
        </div>
      </div>
    </div>
  </Card>
)
