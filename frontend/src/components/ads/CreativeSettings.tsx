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

      <div className="space-y-3">
        <label className="text-xs font-medium text-muted-foreground">Video Length</label>
        <div className="flex flex-wrap gap-4">
          {VIDEO_LENGTH_OPTIONS.map((len) => (
            <label
              key={len}
              className={cn(
                "flex items-center gap-2 cursor-pointer group",
              )}
            >
              <div className="relative flex items-center justify-center">
                <input
                  type="radio"
                  name="videoLength"
                  checked={values.videoLength === len}
                  onChange={() => onChange('videoLength', len)}
                  className="sr-only"
                />
                <div className={cn(
                  "w-4 h-4 rounded-full border transition-all duration-200",
                  values.videoLength === len
                    ? "border-accent bg-accent"
                    : "border-muted-foreground/30 bg-transparent group-hover:border-accent/50"
                )}>
                  {values.videoLength === len && (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <div className="w-1.5 h-1.5 rounded-full bg-slate-900" />
                    </div>
                  )}
                </div>
              </div>
              <span className={cn(
                "text-sm transition-colors",
                values.videoLength === len ? "text-foreground font-medium" : "text-muted-foreground group-hover:text-foreground"
              )}>
                {len === 'custom' ? 'Custom' : `${len}s`}
              </span>
            </label>
          ))}
        </div>
      </div>
    </div>
  )
}
