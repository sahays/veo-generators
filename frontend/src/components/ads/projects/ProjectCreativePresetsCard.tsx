import { useState } from 'react'
import type { UseFormSetValue } from 'react-hook-form'
import { Palette, Camera, Sparkles, Music, FileText } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import {
  type ProjectFormData,
  type CreativePresetOption,
  VISUAL_STYLE_PRESETS_UI,
  COLOR_PALETTE_PRESETS_UI,
  DIRECTOR_STYLE_PRESETS_UI,
} from '@/types/project'

const VISUAL_CATEGORIES = ['All', '3D & Toy', '2D & Anime', 'Cinema'] as const

const VisualStyleOptionButton = ({
  preset,
  isSelected,
  onSelect,
}: {
  preset: CreativePresetOption
  isSelected: boolean
  onSelect: () => void
}) => (
  <Button
    variant="unstyled"
    type="button"
    onClick={onSelect}
    className={cn(
      'flex flex-col items-start gap-1 p-2.5 rounded-[6px] border text-left transition-all',
      isSelected
        ? 'bg-accent/10 border-accent text-foreground shadow-sm'
        : 'border-border text-muted-foreground hover:border-accent/30',
    )}
  >
    <div className="w-full flex items-center justify-between gap-2">
      <span className="text-[11px] font-bold text-foreground">{preset.label}</span>
      <span className="text-[9px] font-mono uppercase px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
        {preset.category}
      </span>
    </div>
    <p className="text-[10px] leading-snug opacity-80">{preset.shortDescription}</p>
  </Button>
)

const VisualStyleSelector = ({ selectedId, setValue }: { selectedId: string; setValue: UseFormSetValue<ProjectFormData> }) => {
  const [activeCategory, setActiveCategory] = useState<string>('All')
  const filtered = activeCategory === 'All' ? VISUAL_STYLE_PRESETS_UI : VISUAL_STYLE_PRESETS_UI.filter((item) => item.category === activeCategory)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-bold text-foreground flex items-center gap-1.5">
            <Sparkles size={13} className="text-accent-dark" /> Visual Medium & Aesthetic Preset
          </p>
          <p className="text-[10px] text-muted-foreground">Injected into Story Architect, Design Studio, and every shot prompt for 9.3 Scene Consistency.</p>
        </div>
        <div className="flex items-center gap-1">
          {VISUAL_CATEGORIES.map((cat) => (
            <Button key={cat} type="button" size="xs" variant={activeCategory === cat ? 'primary' : 'outline'} onClick={() => setActiveCategory(cat)}>{cat}</Button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        {filtered.map((preset) => (
          <VisualStyleOptionButton key={preset.id} preset={preset} isSelected={selectedId === preset.id} onSelect={() => setValue('visual_style_preset', preset.id)} />
        ))}
      </div>
    </div>
  )
}

const ColorPaletteSelector = ({
  selectedId,
  setValue,
}: {
  selectedId: string
  setValue: UseFormSetValue<ProjectFormData>
}) => (
  <div className="space-y-2.5 pt-3 border-t border-border/50">
    <div>
      <p className="text-xs font-bold text-foreground flex items-center gap-1.5">
        <Palette size={13} className="text-accent-dark" /> Color Grading Palette
      </p>
      <p className="text-[10px] text-muted-foreground">
        Locks tonal harmony across character sheets, location anchors, and Veo video clips.
      </p>
    </div>

    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
      {COLOR_PALETTE_PRESETS_UI.map((palette) => {
        const isSelected = selectedId === palette.id
        return (
          <Button
            key={palette.id}
            variant="unstyled"
            type="button"
            onClick={() => setValue('color_palette_preset', palette.id)}
            className={cn(
              'flex flex-col items-start gap-1.5 p-2.5 rounded-[6px] border text-left transition-all',
              isSelected
                ? 'bg-accent/10 border-accent text-foreground shadow-sm'
                : 'border-border text-muted-foreground hover:border-accent/30',
            )}
          >
            <div className="w-full flex items-center justify-between gap-2">
              <span className="text-[11px] font-bold text-foreground truncate">{palette.label}</span>
              <div className="flex items-center gap-1 shrink-0">
                {(palette.swatches || []).map((hex) => (
                  <span key={hex} className="w-2.5 h-2.5 rounded-full border border-border/60" style={{ backgroundColor: hex }} />
                ))}
              </div>
            </div>
            <p className="text-[10px] leading-snug opacity-80">{palette.shortDescription}</p>
          </Button>
        )
      })}
    </div>
  </div>
)

const DirectorOptionButton = ({
  dir,
  isSelected,
  onSelect,
}: {
  dir: CreativePresetOption
  isSelected: boolean
  onSelect: () => void
}) => (
  <Button
    variant="unstyled"
    type="button"
    onClick={onSelect}
    className={cn(
      'flex flex-col items-start gap-1.5 p-2.5 rounded-[6px] border text-left transition-all',
      isSelected
        ? 'bg-accent/10 border-accent text-foreground shadow-sm'
        : 'border-border text-muted-foreground hover:border-accent/30',
    )}
  >
    <span className="text-[11px] font-bold text-foreground">{dir.label}</span>
    <p className="text-[10px] leading-snug opacity-85">{dir.shortDescription}</p>
    <div className="w-full pt-1.5 mt-auto border-t border-border/40 flex flex-wrap gap-1">
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-[9px] font-mono text-foreground">
        <FileText size={9} /> {dir.boundScreenplayLabel}
      </span>
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-muted text-[9px] font-mono text-foreground">
        <Music size={9} /> {dir.boundMusicLabel}
      </span>
    </div>
  </Button>
)

const AutoBoundCrewSummaryBanner = ({ activeDirector }: { activeDirector: CreativePresetOption }) => (
  <div className="p-2.5 rounded-lg bg-muted/40 border border-border/60 flex flex-wrap items-center justify-between gap-2 text-[11px]">
    <div className="flex items-center gap-2">
      <span className="font-mono uppercase text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent-dark font-bold">
        Auto-Bound Crew
      </span>
      <span className="text-muted-foreground">
        Screenwriter: <strong className="text-foreground">{activeDirector.boundScreenplayLabel}</strong> (1-action-at-a-time algorithm)
      </span>
    </div>
    <span className="text-muted-foreground">
      Music & Foley: <strong className="text-foreground">{activeDirector.boundMusicLabel}</strong> (footsteps, wind & action SFX)
    </span>
  </div>
)

const DirectorStyleSelector = ({
  selectedId,
  setValue,
}: {
  selectedId: string
  setValue: UseFormSetValue<ProjectFormData>
}) => {
  const activeDirector = DIRECTOR_STYLE_PRESETS_UI.find((d) => d.id === selectedId) || DIRECTOR_STYLE_PRESETS_UI[0]
  return (
    <div className="space-y-3 pt-3 border-t border-border/50">
      <div>
        <p className="text-xs font-bold text-foreground flex items-center gap-1.5">
          <Camera size={13} className="text-accent-dark" /> Directorial Style (Auto-Binds Screenplay & Soundscape)
        </p>
        <p className="text-[10px] text-muted-foreground">
          Selecting a Directorial Style automatically configures the matching Algorithmic Screenplay & Foley/Music Director preset.
        </p>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
        {DIRECTOR_STYLE_PRESETS_UI.map((dir) => (
          <DirectorOptionButton
            key={dir.id}
            dir={dir}
            isSelected={selectedId === dir.id}
            onSelect={() => {
              setValue('director_style_preset', dir.id)
              if (dir.boundScreenplayId) setValue('screenplay_style_preset', dir.boundScreenplayId)
              if (dir.boundMusicId) setValue('music_style_preset', dir.boundMusicId)
            }}
          />
        ))}
      </div>
      <AutoBoundCrewSummaryBanner activeDirector={activeDirector} />
    </div>
  )
}

export const ProjectCreativePresetsCard = ({
  visualStylePreset,
  colorPalettePreset,
  directorStylePreset,
  setValue,
}: {
  visualStylePreset: string
  colorPalettePreset: string
  directorStylePreset: string
  setValue: UseFormSetValue<ProjectFormData>
}) => (
  <Card title="Creative Direction, Visual Style & Color Palette" icon={Palette}>
    <div className="space-y-4">
      <VisualStyleSelector selectedId={visualStylePreset} setValue={setValue} />
      <ColorPaletteSelector selectedId={colorPalettePreset} setValue={setValue} />
      <DirectorStyleSelector selectedId={directorStylePreset} setValue={setValue} />
    </div>
  </Card>
)
