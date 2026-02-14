import { cn } from '@/lib/utils'
import { CreatableSelect } from './CreatableSelect'
import { VIDEO_LENGTH_OPTIONS, SELECT_LABELS } from '@/types/project'
import type { SelectCategory } from '@/types/project'

interface CreativeSettingsProps {
  values: {
    directorStyle?: string
    cameraMovement?: string
    mood?: string
    location?: string
    characterAppearance?: string
    videoLength: string
  }
  onChange: (field: string, value: string) => void
}

const selectFields: SelectCategory[] = [
  'directorStyle',
  'cameraMovement',
  'mood',
  'location',
  'characterAppearance',
]

export const CreativeSettings = ({ values, onChange }: CreativeSettingsProps) => {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {selectFields.map((field) => (
          <CreatableSelect
            key={field}
            category={field}
            label={SELECT_LABELS[field]}
            value={values[field]}
            onChange={(val) => onChange(field, val)}
            placeholder={`Choose ${SELECT_LABELS[field].toLowerCase()}...`}
          />
        ))}
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">Video Length</label>
        <div className="flex gap-2">
          {VIDEO_LENGTH_OPTIONS.map((len) => (
            <button
              key={len}
              type="button"
              onClick={() => onChange('videoLength', len)}
              className={cn(
                "flex-1 py-2 rounded-lg text-sm font-medium transition-all duration-200 border",
                values.videoLength === len
                  ? "bg-accent text-slate-900 border-accent shadow-sm"
                  : "bg-card border-border text-muted-foreground hover:border-accent/50 hover:text-foreground"
              )}
            >
              {len}s
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
