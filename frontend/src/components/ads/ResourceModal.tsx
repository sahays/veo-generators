import React, { useState, useEffect } from 'react'
import { Modal, Select } from '@/components/UI'
import { Button } from '@/components/Common'
import { FileText, Code, Zap, Loader2 } from 'lucide-react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
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
    { value: 'key-moments', label: 'Key Moments Analysis' }
  ],
  schema: [
    { value: 'project-schema', label: 'Project Analysis Schema' },
    { value: 'scene-schema', label: 'Scene Generation Schema' },
    { value: 'key-moments', label: 'Key Moments Analysis' }
  ]
}

export const ResourceModal = ({
  isOpen,
  onClose,
  onSuccess,
  type,
  initialData,
  existingResources,
  readOnly = false
}: ResourceModalProps) => {
  const [formData, setFormData] = useState({
    name: '',
    category: type === 'prompt' ? 'production-ad' : 'project-schema',
    content: ''
  })
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setFormData({
        name: initialData?.name || '',
        category: initialData?.category || (type === 'prompt' ? 'production-ad' : 'project-schema'),
        content: initialData?.content || ''
      })
    }
  }, [isOpen, initialData, type])

  const handleSave = async () => {
    if (readOnly || !formData.name || !formData.content || !formData.category) return
    
    setLoading(true)
    try {
      const currentCategoryResources = existingResources.filter(
        r => r.category === formData.category && r.type === type
      )
      const nextVersion = currentCategoryResources.length > 0 
        ? Math.max(...currentCategoryResources.map(r => r.version)) + 1 
        : 1

      const newResource = {
        type,
        category: formData.category,
        name: formData.name,
        content: formData.content,
        version: nextVersion,
        is_active: currentCategoryResources.length === 0,
        createdAt: new Date().toISOString()
      }
      const saved = await api.system.createResource(newResource)
      onSuccess(saved)
      onClose()
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const categoryOptions = CATEGORY_OPTIONS[type] || []
  const modalTitle = readOnly 
    ? `View ${type === 'prompt' ? 'Prompt' : 'Schema'}` 
    : (initialData?.id ? `Iterate ${type === 'prompt' ? 'Prompt' : 'Schema'}` : `New ${type === 'prompt' ? 'Prompt' : 'Schema'}`)

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={modalTitle}
      maxWidth="max-w-3xl"
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">Name</label>
            <input
              value={formData.name}
              onChange={e => setFormData({ ...formData, name: e.target.value })}
              disabled={readOnly}
              className="w-full px-3 py-2.5 rounded-lg text-sm bg-background border border-border focus:ring-2 focus:ring-accent/30 outline-none transition-all shadow-sm disabled:opacity-70 disabled:cursor-text"
              placeholder={`e.g. ${type === 'prompt' ? 'Cinematic Analysis v2' : 'Scene Output Structure'}`}
            />
          </div>
          {readOnly ? (
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">Category</label>
              <div className="w-full px-3 py-2.5 rounded-lg text-sm bg-background border border-border text-foreground/80">
                {categoryOptions.find(o => o.value === formData.category)?.label || formData.category}
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
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">Content</label>
          <div className="relative group border border-border rounded-xl overflow-hidden shadow-sm focus-within:ring-2 focus-within:ring-accent/30 transition-all bg-background">
            <div className="absolute top-2 right-2 z-10 opacity-0 group-hover:opacity-100 transition-opacity">
               <div className="px-2 py-1 rounded bg-muted text-[10px] font-mono text-accent-dark font-medium border border-border">
                 {type === 'schema' ? 'JSON' : 'TEXT'}
               </div>
            </div>
            <textarea
              value={formData.content}
              onChange={e => setFormData({ ...formData, content: e.target.value })}
              readOnly={readOnly}
              rows={16}
              className="w-full p-4 font-mono text-xs bg-background text-foreground outline-none resize-none leading-relaxed read-only:cursor-text"
              placeholder={type === 'prompt' ? "Enter your system prompt here..." : "{\n  \"type\": \"object\",\n  ...\n}"}
              spellCheck={false}
            />
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-2 mt-6">
          <Button variant="ghost" onClick={onClose} type="button">{readOnly ? 'Close' : 'Cancel'}</Button>
          {!readOnly && (
            <Button 
              icon={loading ? Loader2 : Zap} 
              onClick={handleSave}
              disabled={loading || !formData.name || !formData.content}
              className={loading ? "opacity-70" : ""}
              type="button"
            >
              {loading ? 'Saving...' : 'Save Resource'}
            </Button>
          )}
        </div>
      </div>
    </Modal>
  )
}
