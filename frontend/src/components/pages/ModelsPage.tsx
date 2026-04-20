import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Cpu, Trash2, Star, Check, X, Loader2, Sprout } from 'lucide-react'
import { api } from '@/lib/api'
import { Button } from '@/components/Common'
import { Modal } from '@/components/Modal'
import { cn } from '@/lib/utils'

interface AIModel {
  id: string
  name: string
  code: string
  provider: string
  capability: string
  regions: string[]
  is_default: boolean
  is_active: boolean
  createdAt: string
}

const CAPABILITIES = [
  { value: 'text', label: 'Text Analysis' },
  { value: 'image', label: 'Image Generation' },
  { value: 'video', label: 'Video Generation' },
]

const PROVIDERS = [
  { value: 'gemini', label: 'Gemini' },
  { value: 'veo', label: 'Veo' },
]

export const ModelsPage = () => {
  const [models, setModels] = useState<AIModel[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [regions, setRegions] = useState<string[]>([])

  // Create form
  const [form, setForm] = useState({
    name: '', code: '', provider: 'gemini', capability: 'text',
    regions: ['global'], is_default: false,
  })

  const load = async () => {
    try {
      const [data, regionList] = await Promise.all([
        api.models.list(),
        api.models.regions(),
      ])
      setModels(data)
      setRegions(regionList)
    } catch (e) {
      console.error('Failed to load models:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleCreate = async () => {
    try {
      await api.models.create(form)
      setShowCreate(false)
      setForm({ name: '', code: '', provider: 'gemini', capability: 'text', regions: ['global'], is_default: false })
      load()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const handleSetDefault = async (id: string) => {
    await api.models.setDefault(id)
    load()
  }

  const handleToggleActive = async (model: AIModel) => {
    await api.models.update(model.id, { is_active: !model.is_active })
    load()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this model?')) return
    await api.models.delete(id)
    load()
  }

  const handleSeed = async () => {
    try {
      await api.models.seed()
      load()
    } catch (e: any) {
      alert(e.message)
    }
  }

  const grouped = CAPABILITIES.map(cap => ({
    ...cap,
    models: models.filter(m => m.capability === cap.value),
  }))

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="animate-spin text-muted-foreground" size={24} />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Cpu size={24} className="text-accent" />
          <h1 className="text-2xl font-heading font-bold">AI Models</h1>
        </div>
        <div className="flex gap-2">
          {models.length === 0 && (
            <Button variant="secondary" icon={Sprout} onClick={handleSeed}>
              Seed Defaults
            </Button>
          )}
          <Button icon={Plus} onClick={() => setShowCreate(true)}>
            Add Model
          </Button>
        </div>
      </div>

      {models.length === 0 && (
        <p className="text-muted-foreground text-sm">
          No models configured yet. Click "Seed Defaults" to add the standard Gemini and Veo models.
        </p>
      )}

      {/* Sections by capability */}
      {grouped.map(group => group.models.length > 0 && (
        <div key={group.value} className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            {group.label}
          </h2>
          <div className="space-y-2">
            {group.models.map((model) => (
              <motion.div
                key={model.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className={cn(
                  "glass bg-card rounded-xl px-4 py-3 flex items-center gap-4",
                  !model.is_active && "opacity-50"
                )}
              >
                {/* Default star */}
                <button
                  onClick={() => handleSetDefault(model.id)}
                  className={cn(
                    "shrink-0 cursor-pointer transition-colors",
                    model.is_default ? "text-amber-500" : "text-muted-foreground/30 hover:text-amber-500/50"
                  )}
                  title={model.is_default ? "Default model" : "Set as default"}
                >
                  <Star size={16} fill={model.is_default ? "currentColor" : "none"} />
                </button>

                {/* Name + code */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">{model.name}</span>
                    <span className={cn(
                      "px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border",
                      model.provider === 'veo'
                        ? "bg-purple-500/10 text-purple-600 border-purple-500/20"
                        : "bg-blue-500/10 text-blue-600 border-blue-500/20"
                    )}>
                      {model.provider}
                    </span>
                    {!model.is_active && (
                      <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-red-500/10 text-red-500 border border-red-500/20">
                        Inactive
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 mt-0.5">
                    <code className="text-xs text-muted-foreground font-mono">{model.code}</code>
                    <span className="text-[10px] text-muted-foreground/60">
                      {model.regions.length === 1 ? model.regions[0] : `${model.regions.length} regions`}
                    </span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => handleToggleActive(model)}
                    className="p-1.5 rounded-lg hover:bg-muted transition-colors cursor-pointer"
                    title={model.is_active ? "Deactivate" : "Activate"}
                  >
                    {model.is_active ? <X size={14} className="text-muted-foreground" /> : <Check size={14} className="text-green-500" />}
                  </button>
                  <button
                    onClick={() => handleDelete(model.id)}
                    className="p-1.5 rounded-lg hover:bg-red-500/10 transition-colors cursor-pointer"
                    title="Delete"
                  >
                    <Trash2 size={14} className="text-red-500" />
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      ))}

      {/* Create Modal */}
      <Modal
        isOpen={showCreate}
        onClose={() => setShowCreate(false)}
        title="Add Model"
        footer={
          <div className="flex gap-2 justify-end">
            <Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button>
            <Button onClick={handleCreate} disabled={!form.name || !form.code}>Create</Button>
          </div>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Name</label>
            <input
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              placeholder="Gemini 3.1 Pro"
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Model Code</label>
            <input
              value={form.code}
              onChange={e => setForm(f => ({ ...f, code: e.target.value }))}
              placeholder="gemini-3.1-pro-preview"
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Provider</label>
              <select
                value={form.provider}
                onChange={e => setForm(f => ({ ...f, provider: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {PROVIDERS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">Capability</label>
              <select
                value={form.capability}
                onChange={e => setForm(f => ({ ...f, capability: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-sm focus:outline-none focus:ring-2 focus:ring-accent"
              >
                {CAPABILITIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Region</label>
            <select
              value={form.regions[0] || 'global'}
              onChange={e => setForm(f => ({ ...f, regions: [e.target.value] }))}
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border text-sm focus:outline-none focus:ring-2 focus:ring-accent"
            >
              {regions.map(r => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={form.is_default}
              onChange={e => setForm(f => ({ ...f, is_default: e.target.checked }))}
              className="rounded"
            />
            <span className="text-sm">Set as default for this capability</span>
          </label>
        </div>
      </Modal>
    </div>
  )
}
