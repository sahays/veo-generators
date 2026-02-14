import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Plus, Trash2, GripVertical } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { useProjectStore } from '@/store/useProjectStore'
import { DEFAULT_OPTIONS, SELECT_LABELS } from '@/types/project'
import type { SelectCategory, CustomOption } from '@/types/project'

interface ConfigSettingsPageProps {
  category: SelectCategory
}

export const ConfigSettingsPage = ({ category }: ConfigSettingsPageProps) => {
  const { getCustomOptions, addCustomOption, customOptions } = useProjectStore()
  const [isModalOpen, setIsModalOpen] = useState(false)

  const defaults = DEFAULT_OPTIONS[category]
  const custom = getCustomOptions(category)
  const label = SELECT_LABELS[category]

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.25 }}
      className="max-w-3xl mx-auto space-y-6"
    >
      <div className="flex items-center justify-between">
        <div className="space-y-1">
          <h2 className="text-xl font-heading text-foreground tracking-tight">{label}</h2>
          <p className="text-xs text-muted-foreground">
            Manage default and custom options for {label.toLowerCase()}.
          </p>
        </div>
        <Button icon={Plus} onClick={() => setIsModalOpen(true)}>
          Add {label.split(' ')[0]}
        </Button>
      </div>

      {/* Default options */}
      <Card title="Defaults" className="overflow-hidden">
        <div className="divide-y divide-border -mx-5 -mb-5 mt-1">
          {defaults.map((name) => (
            <div
              key={name}
              className="flex items-center gap-3 px-5 py-3 text-sm text-foreground"
            >
              <GripVertical size={14} className="text-muted-foreground/40" />
              <span>{name}</span>
              <span className="ml-auto text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                built-in
              </span>
            </div>
          ))}
        </div>
      </Card>

      {/* Custom options */}
      <Card title={`Custom (${custom.length})`} className="overflow-hidden">
        {custom.length === 0 ? (
          <div className="py-8 flex flex-col items-center text-center">
            <p className="text-sm text-muted-foreground">
              No custom {label.toLowerCase()} yet.
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Click "Add" above to create one.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border -mx-5 -mb-5 mt-1">
            {custom.map((opt) => (
              <CustomOptionRow key={opt.id} option={opt} category={category} />
            ))}
          </div>
        )}
      </Card>

      <AnimatePresence>
        {isModalOpen && (
          <AddOptionModal
            label={label}
            existingNames={[...defaults, ...custom.map((o) => o.name)]}
            onConfirm={(name, prompt) => {
              addCustomOption(category, name, prompt)
              setIsModalOpen(false)
            }}
            onClose={() => setIsModalOpen(false)}
          />
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// ─── Row ─────────────────────────────────────────────────────────────────────

const CustomOptionRow = ({
  option,
  category,
}: {
  option: CustomOption
  category: SelectCategory
}) => {
  const removeCustomOption = useProjectStore((s) => s.removeCustomOption)

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      className="flex items-start gap-3 px-5 py-3 group"
    >
      <GripVertical size={14} className="text-muted-foreground/40 mt-1 shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground">{option.name}</p>
        {option.prompt && (
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
            {option.prompt}
          </p>
        )}
      </div>
      <button
        onClick={() => removeCustomOption(category, option.id)}
        className="p-1 rounded-md opacity-0 group-hover:opacity-100 hover:bg-red-500/10 hover:text-red-500 transition-all text-muted-foreground shrink-0"
      >
        <Trash2 size={14} />
      </button>
    </motion.div>
  )
}

// ─── Modal ───────────────────────────────────────────────────────────────────

interface AddOptionModalProps {
  label: string
  existingNames: string[]
  onConfirm: (name: string, prompt: string) => void
  onClose: () => void
}

const AddOptionModal = ({ label, existingNames, onConfirm, onClose }: AddOptionModalProps) => {
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const duplicate = existingNames.includes(name.trim())

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
    >
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
      />

      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 10 }}
        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        className="relative w-full max-w-md glass bg-card rounded-xl shadow-2xl border border-border overflow-hidden"
      >
        <div className="px-5 pt-5 pb-3">
          <h3 className="text-base font-heading font-bold text-foreground">
            New {label}
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            This will be saved and available across all projects.
          </p>
        </div>

        <div className="px-5 pb-2 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim() && !duplicate) {
                  e.preventDefault()
                  onConfirm(name.trim(), prompt.trim())
                }
                if (e.key === 'Escape') onClose()
              }}
              placeholder={`e.g. My custom ${label.toLowerCase()}`}
              className={cn(
                "w-full px-3 py-2 rounded-lg text-sm transition-all duration-200 text-foreground",
                "bg-muted border border-border placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/50",
                duplicate && "border-red-500/50 focus:ring-red-500/30"
              )}
            />
            {duplicate && (
              <p className="text-[11px] text-red-500">This name already exists.</p>
            )}
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Prompt / Description
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') onClose()
              }}
              rows={3}
              placeholder="Describe the style, behavior, or details..."
              className={cn(
                "w-full px-3 py-2 rounded-lg text-sm transition-all duration-200 resize-none text-foreground",
                "bg-muted border border-border placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/50"
              )}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-border mt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onConfirm(name.trim(), prompt.trim())}
            disabled={!name.trim() || duplicate}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200",
              "bg-accent text-slate-900 hover:bg-accent-dark shadow-sm",
              "disabled:opacity-40 disabled:cursor-not-allowed"
            )}
          >
            Create
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}
