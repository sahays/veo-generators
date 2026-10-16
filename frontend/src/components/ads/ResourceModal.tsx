import { useState, useEffect } from 'react'
import { Modal, Select } from '@/components/UI'
import { Button } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Zap, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { systemResourceFormSchema } from '@/types/schemas'
import { useToastStore } from '@/store/useToastStore'
import type { SystemResource } from '@/types/project'

interface ResourceModalProps {
  isOpen: boolean
  onClose: () => void
  onSuccess: (resource: SystemResource) => void
  type: 'prompt' | 'schema'
  initialData?: Partial<SystemResource>
  existingResources: SystemResource[]
  readOnly?: boolean
}

const CATEGORY_OPTIONS = {
  prompt: [
    { value: 'production-movie', label: 'Movie Production' },
    { value: 'production-ad', label: 'Ad Production' },
    { value: 'production-social', label: 'Social Production' },
    { value: 'key-moments', label: 'Key Moments Analysis' },
    { value: 'thumbnails', label: 'Thumbnail Analysis' },
    { value: 'collage', label: 'Thumbnail Collage' },
    { value: 'orientation', label: 'Orientation / Reframe' },
    { value: 'promo', label: 'Promo Generation' },
  ],
  schema: [
    { value: 'project-schema', label: 'Project Analysis Schema' },
    { value: 'scene-schema', label: 'Scene Generation Schema' },
    { value: 'key-moments', label: 'Key Moments Analysis' },
  ],
}

export const ResourceModal = ({
  isOpen,
  onClose,
  onSuccess,
  type,
  initialData,
  existingResources,
  readOnly = false,
}: ResourceModalProps) => {
  const [formData, setFormData] = useState({
    name: '',
    category: type === 'prompt' ? 'production-ad' : 'project-schema',
    content: '',
  })
  const [formError, setFormError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const addToast = useToastStore((s) => s.addToast)

  useEffect(() => {
    if (isOpen) {
      setFormData({
        name: initialData?.name || '',
        category:
          initialData?.category ||
          (type === 'prompt' ? 'production-ad' : 'project-schema'),
        content: initialData?.content || '',
      })
      setFormError(null)
    }
  }, [isOpen, initialData, type])

  const handleSave = async () => {
    if (readOnly) return
    const parsed = systemResourceFormSchema.safeParse({
      type,
      ...formData,
    })
    if (!parsed.success) {
      setFormError(parsed.error.issues[0]?.message || 'Invalid resource fields')
      return
    }

    setLoading(true)
    setFormError(null)
    try {
      const currentCategoryResources = existingResources.filter(
        (r) => r.category === parsed.data.category && r.type === type,
      )
      const nextVersion =
        currentCategoryResources.length > 0
          ? Math.max(...currentCategoryResources.map((r) => r.version)) + 1
          : 1

      const newResource = {
        type,
        category: parsed.data.category,
        name: parsed.data.name,
        content: parsed.data.content,
        version: nextVersion,
        is_active: currentCategoryResources.length === 0,
        createdAt: new Date().toISOString(),
      }
      const saved = await api.system.createResource(newResource)
      addToast({
        title: `${type === 'prompt' ? 'Prompt' : 'Schema'} saved`,
        description: `${saved.name} (v${saved.version})`,
        variant: 'success',
      })
      onSuccess(saved)
      onClose()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to save resource')
    } finally {
      setLoading(false)
    }
  }

  const categoryOptions = CATEGORY_OPTIONS[type] || []
  const modalTitle = readOnly
    ? `View ${type === 'prompt' ? 'Prompt' : 'Schema'}`
    : initialData?.id
      ? `Iterate ${type === 'prompt' ? 'Prompt' : 'Schema'}`
      : `New ${type === 'prompt' ? 'Prompt' : 'Schema'}`

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={modalTitle}
      maxWidth="max-w-3xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} type="button">
            {readOnly ? 'Close' : 'Cancel'}
          </Button>
          {!readOnly && (
            <Button
              icon={loading ? Loader2 : Zap}
              onClick={handleSave}
              disabled={loading || !formData.name || !formData.content}
              type="button"
            >
              {loading ? 'Saving...' : 'Save Resource'}
            </Button>
          )}
        </>
      }
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Input
            label="Name"
            value={formData.name}
            onChange={(e) => {
              setFormData({ ...formData, name: e.target.value })
              setFormError(null)
            }}
            disabled={readOnly}
            placeholder={`e.g. ${type === 'prompt' ? 'Cinematic Analysis v2' : 'Scene Output Structure'}`}
          />
          {readOnly ? (
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1 block">
                Category
              </label>
              <div className="w-full px-3.5 py-2.5 rounded-lg text-sm bg-card border border-border text-foreground/80">
                {categoryOptions.find((o) => o.value === formData.category)?.label ||
                  formData.category}
              </div>
            </div>
          ) : (
            <Select
              label="Category"
              value={formData.category}
              onChange={(val) => setFormData({ ...formData, category: val })}
              options={categoryOptions}
              className="w-full"
            />
          )}
        </div>

        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1 block">
            Content
          </label>
          <div className="relative group border border-border rounded-xl overflow-hidden shadow-sm focus-within:ring-2 focus-within:ring-accent/25 transition-all bg-card">
            <div className="absolute top-2.5 right-2.5 z-10 opacity-75 group-hover:opacity-100 transition-opacity">
              <Badge variant="accent" className="font-mono">
                {type === 'schema' ? 'JSON' : 'TEXT'}
              </Badge>
            </div>
            <Textarea
              value={formData.content}
              onChange={(e) => {
                setFormData({ ...formData, content: e.target.value })
                setFormError(null)
              }}
              readOnly={readOnly}
              rows={15}
              className="w-full p-4 font-mono text-xs bg-transparent border-none shadow-none focus-visible:ring-0 text-foreground outline-none resize-none leading-relaxed read-only:cursor-text"
              placeholder={
                type === 'prompt'
                  ? 'Enter your system prompt here...'
                  : '{\n  "type": "object",\n  ...\n}'
              }
              spellCheck={false}
            />
          </div>
        </div>

        {formError && <p className="text-xs text-red-500">{formError}</p>}
      </div>
    </Modal>
  )
}
