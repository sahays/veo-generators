import { PRESET_CATALOG, type Gender } from '@/types/avatar'

type GenderFilter = 'all' | Gender

interface Props {
  presetName: string
  setPresetName: (id: string) => void
  genderFilter: GenderFilter
  setGenderFilter: (g: GenderFilter) => void
  filteredPresets: typeof PRESET_CATALOG
}

export const AvatarPresetGrid = ({
  presetName,
  setPresetName,
  genderFilter,
  setGenderFilter,
  filteredPresets,
}: Props) => (
  <div>
    <div className="flex items-center justify-between mb-2">
      <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
        Avatar
      </label>
      <GenderChips value={genderFilter} onChange={setGenderFilter} />
    </div>
    <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
      {filteredPresets.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() => setPresetName(p.id)}
          className={`relative aspect-[3/4] rounded-lg overflow-hidden border-2 transition-colors text-left ${
            presetName === p.id
              ? 'border-accent shadow-lg'
              : 'border-transparent hover:border-accent/40'
          }`}
          title={`${p.displayName} — ${p.mood}`}
        >
          <img
            src={p.imageUrl}
            alt={p.displayName}
            className="absolute inset-0 w-full h-full object-cover"
          />
          <div className="absolute inset-x-0 bottom-0 px-2 py-1 bg-gradient-to-t from-black/80 to-transparent">
            <div className="text-xs font-medium text-white">{p.displayName}</div>
          </div>
        </button>
      ))}
    </div>
  </div>
)

const GenderChips = ({
  value,
  onChange,
}: {
  value: GenderFilter
  onChange: (next: GenderFilter) => void
}) => {
  const options: { id: GenderFilter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'female', label: 'Female' },
    { id: 'male', label: 'Male' },
  ]
  return (
    <div className="flex items-center gap-1">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          onClick={() => onChange(o.id)}
          className={`px-2 py-0.5 rounded-full text-[10px] font-medium uppercase tracking-wider transition-colors ${
            value === o.id
              ? 'bg-accent text-accent-foreground'
              : 'bg-muted text-muted-foreground hover:bg-muted/70'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
