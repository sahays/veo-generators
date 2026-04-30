import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { X, Loader2, Save } from 'lucide-react'
import { Button } from '@/components/Common'
import { Select } from '@/components/UI'
import { api } from '@/lib/api'
import type { Avatar, AvatarStyle } from '@/types/avatar'
import { STYLE_LABELS } from '@/types/avatar'

const STYLE_OPTIONS: { value: AvatarStyle; label: string; description: string }[] = [
  { value: 'to_the_point', label: STYLE_LABELS.to_the_point, description: 'Minimal words, direct, no preamble' },
  { value: 'talkative', label: STYLE_LABELS.talkative, description: 'Friendly, warm, expressive' },
  { value: 'funny', label: STYLE_LABELS.funny, description: 'Light, playful, a touch of humor' },
  { value: 'serious', label: STYLE_LABELS.serious, description: 'Measured, factual, no jokes' },
  { value: 'cynical', label: STYLE_LABELS.cynical, description: 'Wry, slightly skeptical, dry tone' },
]

interface AvatarEditModalProps {
  avatar: Avatar
  onClose: () => void
  onSaved: (updated: Pick<Avatar, 'name' | 'style' | 'persona_prompt'>) => void
}

export const AvatarEditModal = ({ avatar, onClose, onSaved }: AvatarEditModalProps) => {
  const [name, setName] = useState(avatar.name)
  const [style, setStyle] = useState<AvatarStyle>(avatar.style)
  const [persona, setPersona] = useState(avatar.persona_prompt || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await api.avatars.update(avatar.id, {
        name: name.trim(),
        style,
        persona_prompt: persona,
      })
      onSaved({ name: name.trim(), style, persona_prompt: persona })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
      setSaving(false)
    }
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
      >
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 20, scale: 0.95 }}
          onClick={(e) => e.stopPropagation()}
          className="glass bg-card rounded-2xl shadow-2xl border border-border w-full max-w-md p-6"
        >
          <div className="flex items-center justify-between mb-5">
            <h3 className="text-lg font-heading font-bold text-foreground">Edit avatar</h3>
            <button
              onClick={onClose}
              className="p-1 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            >
              <X size={18} />
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-1.5 block">
                Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 text-sm"
                required
              />
            </div>

            <Select
              label="Tone"
              value={style}
              onChange={(v) => setStyle(v as AvatarStyle)}
              options={STYLE_OPTIONS}
            />

            <div>
              <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-1.5 block">
                Persona
              </label>
              <textarea
                value={persona}
                onChange={(e) => setPersona(e.target.value)}
                rows={4}
                placeholder="Describe how this avatar should respond. e.g. A senior product manager at a tech startup answering questions about AI."
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 text-sm resize-y"
              />
              <p className="text-[10px] text-muted-foreground mt-1">
                Injected into Gemini's system prompt on every turn. Leave empty for generic behavior.
              </p>
            </div>

            {error && (
              <div className="p-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">
                {error}
              </div>
            )}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="px-3 py-2 rounded-lg text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                Cancel
              </button>
              <Button type="submit" icon={saving ? Loader2 : Save} disabled={saving || !name.trim()}>
                {saving ? 'Saving…' : 'Save'}
              </Button>
            </div>
          </form>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
