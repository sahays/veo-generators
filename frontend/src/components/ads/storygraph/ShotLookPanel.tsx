import { cn } from '@/lib/utils'
import { Badge } from '@/components/Common'
import type {
  StoryGraphColorGradeSpec,
  StoryGraphLightingSpec,
  StoryGraphScene,
  StoryGraphShot,
  StoryGraphShotLook,
} from '@/types/project'

const ClipPromptSection = ({ prompt }: { prompt: string }) => (
  <div className="space-y-1">
    <div className="flex items-center gap-1.5">
      <Badge variant="accent" className="font-mono font-bold uppercase text-[9px] px-1.5 py-0">
        Omni clip prompt
      </Badge>
    </div>
    <p className="rounded-lg bg-black/40 border border-accent/20 p-2 text-[11px] font-mono text-foreground/90 leading-relaxed break-words">
      {prompt}
    </p>
  </div>
)

const LightingLookSection = ({
  lighting,
}: {
  lighting?: StoryGraphLightingSpec | null
}) => {
  if (!lighting) return null
  const items = [
    { label: 'Key', val: lighting.key },
    { label: 'Fill', val: lighting.fill },
    { label: 'Practicals', val: lighting.practicals },
    { label: 'Direction', val: lighting.direction },
    { label: 'Quality', val: lighting.quality },
  ].filter((item) => Boolean(item.val && item.val.trim()))

  if (items.length === 0) return null

  return (
    <div className="space-y-1">
      <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
        Lighting
      </span>
      <div className="flex flex-wrap gap-1.5">
        {items.map((it) => (
          <Badge key={it.label} variant="default" className="font-mono text-[10px] font-normal">
            <span className="text-muted-foreground mr-1">{it.label}:</span>
            {it.val}
          </Badge>
        ))}
      </div>
    </div>
  )
}

const ColorGradeSection = ({
  colorGrade,
}: {
  colorGrade?: StoryGraphColorGradeSpec | null
}) => {
  if (!colorGrade) return null
  const shadesStr = (colorGrade.shades || []).filter(Boolean).join(', ')
  const items = [
    { label: 'Shades', val: shadesStr },
    { label: 'Contrast', val: colorGrade.contrast },
    { label: 'Saturation', val: colorGrade.saturation },
    { label: 'Temperature', val: colorGrade.temperature },
  ].filter((item) => Boolean(item.val && item.val.trim()))

  if (items.length === 0) return null

  return (
    <div className="space-y-1">
      <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-muted-foreground">
        Color Grade
      </span>
      <div className="flex flex-wrap gap-1.5">
        {items.map((it) => (
          <Badge key={it.label} variant="default" className="font-mono text-[10px] font-normal">
            <span className="text-muted-foreground mr-1">{it.label}:</span>
            {it.val}
          </Badge>
        ))}
      </div>
    </div>
  )
}

const CinematographyTagsSection = ({
  look,
}: {
  look?: StoryGraphShotLook | null
}) => {
  if (!look) return null
  const tags = [
    { label: 'Mood', val: look.mood },
    { label: 'Composition', val: look.composition },
    { label: 'Camera Intent', val: look.camera_motion_intent },
  ].filter((t) => Boolean(t.val && t.val.trim()))

  if (tags.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5 pt-0.5">
      {tags.map((t) => (
        <Badge key={t.label} variant="accent" className="font-mono text-[10px]">
          <span className="opacity-75 mr-1">{t.label}:</span>
          {t.val}
        </Badge>
      ))}
    </div>
  )
}

export const findOmniPrompt = (
  scenes: StoryGraphScene[] | undefined,
  shot: StoryGraphShot,
): string | null => {
  if (shot.clip_index === null || shot.clip_index === undefined || !scenes) {
    return null
  }
  const scene = scenes.find((s) => s.id === shot.scene_id)
  const clip = scene?.clips?.find((c) => c.clip_index === shot.clip_index)
  const prompt = clip?.omni_prompt?.trim()
  return prompt && prompt.length > 0 ? prompt : null
}

const hasVisibleLook = (look?: StoryGraphShotLook | null): boolean => {
  if (!look) return false
  const hasText = Boolean(
    look.mood?.trim() ||
      look.composition?.trim() ||
      look.camera_motion_intent?.trim(),
  )
  const lt = look.lighting
  const hasLight = Boolean(
    lt &&
      (lt.key?.trim() ||
        lt.fill?.trim() ||
        lt.practicals?.trim() ||
        lt.direction?.trim() ||
        lt.quality?.trim()),
  )
  const cg = look.color_grade
  const hasCg = Boolean(
    cg &&
      (cg.contrast?.trim() ||
        cg.saturation?.trim() ||
        cg.temperature?.trim() ||
        (cg.shades || []).length > 0),
  )
  return hasText || hasLight || hasCg
}

export interface ShotLookPanelProps {
  shot: StoryGraphShot
  scenes?: StoryGraphScene[]
  className?: string
}

export const ShotLookPanel = ({
  shot,
  scenes,
  className,
}: ShotLookPanelProps) => {
  const omniPrompt = findOmniPrompt(scenes, shot)
  const showLook = hasVisibleLook(shot.look)

  if (!omniPrompt && !showLook) return null

  return (
    <div
      className={cn(
        'rounded-xl bg-muted/30 border border-border/60 p-3 space-y-2.5 text-xs',
        className,
      )}
    >
      {omniPrompt && <ClipPromptSection prompt={omniPrompt} />}
      {shot.look?.lighting && <LightingLookSection lighting={shot.look.lighting} />}
      {shot.look?.color_grade && <ColorGradeSection colorGrade={shot.look.color_grade} />}
      {showLook && <CinematographyTagsSection look={shot.look} />}
    </div>
  )
}
