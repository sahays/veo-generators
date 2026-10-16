import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { PresetBundle } from '@/types/project'

const ALL_RATIOS = [
  '1:1', '16:9', '9:16', '4:3', '3:4', '4:5', '5:4',
  '2:3', '3:2', '21:9', '1:4', '4:1', '1:8', '8:1',
]

const RATIO_DIMENSIONS: Record<string, { w: number; h: number }> = {
  '1:1': { w: 1, h: 1 },
  '16:9': { w: 16, h: 9 },
  '9:16': { w: 9, h: 16 },
  '4:3': { w: 4, h: 3 },
  '3:4': { w: 3, h: 4 },
  '4:5': { w: 4, h: 5 },
  '5:4': { w: 5, h: 4 },
  '2:3': { w: 2, h: 3 },
  '3:2': { w: 3, h: 2 },
  '21:9': { w: 21, h: 9 },
  '1:4': { w: 1, h: 4 },
  '4:1': { w: 4, h: 1 },
  '1:8': { w: 1, h: 8 },
  '8:1': { w: 8, h: 1 },
}

interface AspectRatioSelectorProps {
  selected: string[]
  onChange: (ratios: string[]) => void
  presets: Record<string, PresetBundle>
}

export function AspectRatioSelector({
  selected,
  onChange,
  presets,
}: AspectRatioSelectorProps): JSX.Element {
  const toggleRatio = (ratio: string) => {
    if (selected.includes(ratio)) {
      onChange(selected.filter((r) => r !== ratio))
    } else {
      onChange([...selected, ratio])
    }
  }

  const applyPreset = (presetId: string) => {
    const preset = presets[presetId]
    if (!preset) return
    const allSelected = preset.ratios.every((r) => selected.includes(r))
    if (allSelected) {
      onChange(selected.filter((r) => !preset.ratios.includes(r)))
    } else {
      const merged = [...new Set([...selected, ...preset.ratios])]
      onChange(merged)
    }
  }

  const isPresetActive = (presetId: string) => {
    const preset = presets[presetId]
    return preset?.ratios.every((r) => selected.includes(r)) ?? false
  }

  return (
    <div className="space-y-4">
      {Object.keys(presets).length > 0 && (
        <div className="space-y-2">
          <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            Presets
          </h4>
          <div className="flex gap-2 flex-wrap">
            {Object.entries(presets).map(([id, preset]) => (
              <Button
                key={id}
                variant={isPresetActive(id) ? 'outline' : 'secondary'}
                size="sm"
                onClick={() => applyPreset(id)}
                className={cn(
                  isPresetActive(id) &&
                    'border-accent bg-accent/10 text-accent-dark',
                )}
              >
                {preset.name}
                <span className="ml-1 text-[10px] opacity-60">
                  ({preset.ratios.length})
                </span>
              </Button>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-2">
        <h4 className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
          Aspect Ratios {selected.length > 0 && `(${selected.length} selected)`}
        </h4>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
          {ALL_RATIOS.map((ratio) => {
            const dims = RATIO_DIMENSIONS[ratio]
            const isSelected = selected.includes(ratio)
            const scale = 36 / Math.max(dims.w, dims.h)
            const pw = Math.round(dims.w * scale)
            const ph = Math.round(dims.h * scale)

            return (
              <Button
                key={ratio}
                variant="unstyled"
                onClick={() => toggleRatio(ratio)}
                className={cn(
                  'flex flex-col items-center gap-2 p-3 rounded-[6px] border transition-all',
                  isSelected
                    ? 'border-accent bg-accent/10 text-accent-dark'
                    : 'border-border bg-card text-muted-foreground hover:border-accent/40 hover:text-foreground',
                )}
              >
                <div
                  className={cn(
                    'rounded-xs border transition-colors',
                    isSelected ? 'border-accent bg-accent/20' : 'border-muted-foreground/30 bg-muted/50',
                  )}
                  style={{ width: pw, height: ph }}
                />
                <span className="text-xs font-medium">{ratio}</span>
              </Button>
            )
          })}
        </div>
      </div>
    </div>
  )
}
