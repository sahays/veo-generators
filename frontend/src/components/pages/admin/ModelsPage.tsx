import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Plus, Cpu, Trash2, Star, Check, X, Loader2, Sprout } from 'lucide-react'
import { api } from '@/hooks/useApiClient'
import { Button } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/select'
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

const ModelRowCard = ({
  model,
  onSetDefault,
  onToggleActive,
  onDelete,
}: {
  model: AIModel
  onSetDefault: (id: string) => void
  onToggleActive: (model: AIModel) => void
  onDelete: (id: string) => void
}) => (
  <motion.div
    initial={{ opacity: 0, y: 8 }}
    animate={{ opacity: 1, y: 0 }}
    className={cn(
      'glass bg-card rounded-xl px-4 py-3 flex items-center gap-4',
      !model.is_active && 'opacity-50',
    )}
  >
    <Button
      variant="ghost"
      size="icon"
      onClick={() => onSetDefault(model.id)}
      className={cn(
        'h-7 w-7 shrink-0 cursor-pointer transition-colors',
        model.is_default ? 'text-amber-500' : 'text-muted-foreground/30 hover:text-amber-500/50',
      )}
      title={model.is_default ? 'Default model' : 'Set as default'}
    >
      <Star size={16} fill={model.is_default ? 'currentColor' : 'none'} />
    </Button>
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">{model.name}</span>
        <span
          className={cn(
            'px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider border',
            model.provider === 'veo'
              ? 'bg-purple-500/10 text-purple-600 border-purple-500/20'
              : 'bg-blue-500/10 text-blue-600 border-blue-500/20',
          )}
        >
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
    <div className="flex items-center gap-1 shrink-0">
      <Button
        variant="ghost"
        size="icon"
        onClick={() => onToggleActive(model)}
        className="h-7 w-7 cursor-pointer"
        title={model.is_active ? 'Deactivate' : 'Activate'}
      >
        {model.is_active ? <X size={14} className="text-muted-foreground" /> : <Check size={14} className="text-green-500" />}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        onClick={() => onDelete(model.id)}
        className="h-7 w-7 hover:bg-red-500/10 cursor-pointer"
        title="Delete"
      >
        <Trash2 size={14} className="text-red-500" />
      </Button>
    </div>
  </motion.div>
)

type CreateModelForm = {
  name: string
  code: string
  provider: string
  capability: string
  regions: string[]
  is_default: boolean
}

const DEFAULT_FORM: CreateModelForm = {
  name: '',
  code: '',
  provider: 'gemini',
  capability: 'text',
  regions: ['global'],
  is_default: false,
}

const CreateModelModalFields = ({
  form,
  setForm,
  regions,
}: {
  form: CreateModelForm
  setForm: React.Dispatch<React.SetStateAction<CreateModelForm>>
  regions: string[]
}) => (
  <div className="space-y-4">
    <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1">Name</label>
      <Input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} placeholder="Gemini 3.8 Flash" />
    </div>
    <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1">Model Code</label>
      <Input value={form.code} onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} placeholder="gemini-3.8-flash" className="font-mono" />
    </div>
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1">Provider</label>
        <NativeSelect value={form.provider} onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}>
          {PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </NativeSelect>
      </div>
      <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1">Capability</label>
        <NativeSelect value={form.capability} onChange={(e) => setForm((f) => ({ ...f, capability: e.target.value }))}>
          {CAPABILITIES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </NativeSelect>
      </div>
    </div>
    <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1">Region</label>
      <NativeSelect value={form.regions[0] || 'global'} onChange={(e) => setForm((f) => ({ ...f, regions: [e.target.value] }))}>
        {regions.map((r) => (
          <option key={r} value={r}>{r}</option>
        ))}
      </NativeSelect>
    </div>
    <label className="flex items-center gap-2 cursor-pointer">
      <input
        type="checkbox"
        checked={form.is_default}
        onChange={(e) => setForm((f) => ({ ...f, is_default: e.target.checked }))}
        className="rounded"
      />
      <span className="text-sm">Set as default for this capability</span>
    </label>
  </div>
)

function useModelsData() {
  const [models, setModels] = useState<AIModel[]>([])
  const [loading, setLoading] = useState(true)
  const [regions, setRegions] = useState<string[]>([])

  const load = useCallback(async () => {
    try {
      const [data, regionList] = await Promise.all([api.models.list(), api.models.regions()])
      setModels(data)
      setRegions(regionList)
    } catch {
      // ignore load error
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleSetDefault = async (id: string) => { await api.models.setDefault(id); load() }
  const handleToggleActive = async (model: AIModel) => { await api.models.update(model.id, { is_active: !model.is_active }); load() }
  const handleDelete = async (id: string) => { if (confirm('Delete this model?')) { await api.models.delete(id); load() } }
  const handleSeed = async () => {
    try { await api.models.seed(); load() } catch (e: unknown) { alert(e instanceof Error ? e.message : 'Seed failed') }
  }
  return { models, loading, regions, load, handleSetDefault, handleToggleActive, handleDelete, handleSeed }
}

const ModelsGroupedList = ({
  models,
  onSetDefault,
  onToggleActive,
  onDelete,
}: {
  models: AIModel[]
  onSetDefault: (id: string) => void
  onToggleActive: (model: AIModel) => void
  onDelete: (id: string) => void
}) => (
  <>
    {CAPABILITIES.map((cap) => ({ ...cap, models: models.filter((m) => m.capability === cap.value) })).map(
      (group) =>
        group.models.length > 0 && (
          <div key={group.value} className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">{group.label}</h2>
            <div className="space-y-2">
              {group.models.map((model) => (
                <ModelRowCard key={model.id} model={model} onSetDefault={onSetDefault} onToggleActive={onToggleActive} onDelete={onDelete} />
              ))}
            </div>
          </div>
        ),
    )}
  </>
)

export const ModelsPage = () => {
  const { models, loading, regions, load, handleSetDefault, handleToggleActive, handleDelete, handleSeed } = useModelsData()
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<CreateModelForm>(DEFAULT_FORM)
  const handleCreate = async () => {
    try {
      await api.models.create(form)
      setShowCreate(false); setForm(DEFAULT_FORM); load()
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : 'Create failed')
    }
  }
  if (loading) return <div className="flex items-center justify-center py-20"><Loader2 className="animate-spin text-muted-foreground" size={24} /></div>
  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3"><Cpu size={24} className="text-accent" /><h1 className="text-2xl font-heading font-bold">AI Models</h1></div>
        <div className="flex gap-2">
          {models.length === 0 && <Button variant="secondary" icon={Sprout} onClick={handleSeed}>Seed Defaults</Button>}
          <Button icon={Plus} onClick={() => setShowCreate(true)}>Add Model</Button>
        </div>
      </div>
      {models.length === 0 && <p className="text-muted-foreground text-sm">No models configured yet. Click &quot;Seed Defaults&quot; to add the standard Gemini and Veo models.</p>}
      <ModelsGroupedList models={models} onSetDefault={handleSetDefault} onToggleActive={handleToggleActive} onDelete={handleDelete} />
      <Modal isOpen={showCreate} onClose={() => setShowCreate(false)} title="Add Model" footer={<div className="flex gap-2 justify-end"><Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button><Button onClick={handleCreate} disabled={!form.name || !form.code}>Create</Button></div>}>
        <CreateModelModalFields form={form} setForm={setForm} regions={regions} />
      </Modal>
    </div>
  )
}

