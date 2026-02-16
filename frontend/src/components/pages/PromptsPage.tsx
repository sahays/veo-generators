import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  FileText, Code, Plus,
  Copy, Loader2, Eye
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import { ResourceModal } from '@/components/ads/ResourceModal'
import type { SystemResource } from '@/types/project'

const RESPONSE_SCHEMA = {
  type: "object",
  properties: {
    scenes: {
      type: "array",
      items: {
        type: "object",
        properties: {
          visual_description: { type: "string" },
          timestamp_start: { type: "string" },
          timestamp_end: { type: "string" },
          metadata: {
            type: "object",
            properties: {
              location: { type: "string" },
              characters: {
                type: "array",
                items: { type: "string" },
                description: "List of all characters, including main actors and background NPCs",
              },
              camera_angle: { type: "string" },
              lighting: { type: "string" },
              style: { type: "string" },
              mood: { type: "string" },
            },
          },
        },
        required: ["visual_description", "timestamp_start", "timestamp_end"],
      },
    },
  },
  required: ["scenes"],
}

export const PromptsPage = () => {
  const [resources, setResources] = useState<SystemResource[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'prompt' | 'schema'>('prompt')
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [selectedInitialData, setSelectedInitialData] = useState<Partial<SystemResource> | undefined>()
  const [isReadOnly, setIsReadOnly] = useState(false)

  const fetchResources = async () => {
    setLoading(true)
    try {
      const data = await api.system.listResources()
      setResources(data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchResources()
  }, [])

  const filteredResources = resources.filter(r => r.type === 'prompt')

  const handleCreateNew = () => {
    setSelectedInitialData(undefined)
    setIsReadOnly(false)
    setIsModalOpen(true)
  }

  const handleIterate = (res: SystemResource) => {
    setSelectedInitialData({
      ...res,
      name: `${res.name} (v${res.version + 1} Draft)`
    })
    setIsReadOnly(false)
    setIsModalOpen(true)
  }

  const handleView = (res: SystemResource) => {
    setSelectedInitialData(res)
    setIsReadOnly(true)
    setIsModalOpen(true)
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div className="space-y-1">
          <h2 className="text-xl font-heading font-bold tracking-tight text-foreground">System Prompts</h2>
          <p className="text-xs text-muted-foreground max-w-lg">
            Manage the prompts and schemas that power the video generation pipeline.
          </p>
        </div>
        <div className="flex bg-muted/50 p-1 rounded-xl border border-border">
          <TabButton
            active={activeTab === 'prompt'}
            onClick={() => setActiveTab('prompt')}
            icon={FileText}
            label="Prompts"
          />
          <TabButton
            active={activeTab === 'schema'}
            onClick={() => setActiveTab('schema')}
            icon={Code}
            label="Response Schema"
          />
        </div>
      </div>

      {activeTab === 'prompt' && (
        <>
          {/* Create button */}
          <div className="flex justify-end">
            <Button icon={Plus} onClick={handleCreateNew}>
              Create New Prompt
            </Button>
          </div>

          {/* Prompt grid */}
          {loading ? (
            <div className="flex flex-col items-center justify-center py-24 gap-4">
              <Loader2 className="animate-spin text-accent" size={32} />
              <p className="text-xs font-medium text-muted-foreground animate-pulse">Loading prompts...</p>
            </div>
          ) : filteredResources.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-24 gap-4">
              <FileText className="text-muted-foreground/30" size={40} />
              <p className="text-sm text-muted-foreground">No prompts yet. Create one to get started.</p>
            </div>
          ) : (
            <div className="border border-border rounded-xl overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/30">
                    <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Name</th>
                    <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Category</th>
                    <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Version</th>
                    <th className="text-left px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Created</th>
                    <th className="text-right px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredResources.map((res) => (
                    <motion.tr
                      key={res.id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="border-b border-border/50 last:border-b-0 hover:bg-muted/20 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <span className="font-medium text-foreground">{res.name}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="bg-muted px-2 py-0.5 rounded text-[10px] font-mono text-muted-foreground capitalize">
                          {res.category}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="bg-muted px-2 py-0.5 rounded text-[10px] font-mono text-muted-foreground">
                          v{res.version}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {new Date(res.createdAt).toLocaleDateString()}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <button
                            onClick={() => handleView(res)}
                            className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                            title="View"
                          >
                            <Eye size={15} />
                          </button>
                          <button
                            onClick={() => handleIterate(res)}
                            className="p-1.5 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                            title="Iterate"
                          >
                            <Copy size={15} />
                          </button>
                        </div>
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {activeTab === 'schema' && (
        <div className="space-y-3">
          <p className="text-xs text-muted-foreground">
            The response schema used by Gemini to structure scene analysis output. This schema is fixed to ensure UI compatibility.
          </p>
          <div className="relative border border-border rounded-xl overflow-hidden bg-muted/20">
            <div className="absolute top-3 right-3 z-10">
              <span className="px-2 py-1 rounded bg-muted text-[10px] font-mono text-accent-dark font-medium border border-border">
                JSON Schema
              </span>
            </div>
            <pre className="p-6 font-mono text-xs text-foreground/80 leading-relaxed overflow-x-auto">
{JSON.stringify(RESPONSE_SCHEMA, null, 2)}
            </pre>
          </div>
        </div>
      )}

      {/* Modal — only used for prompts */}
      <ResourceModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchResources}
        type="prompt"
        initialData={selectedInitialData}
        existingResources={resources}
        readOnly={isReadOnly}
      />
    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

const TabButton = ({ active, onClick, icon: Icon, label }: any) => (
  <button
    onClick={onClick}
    className={cn(
      "flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all duration-200 cursor-pointer",
      active ? "bg-card text-foreground shadow-sm ring-1 ring-border" : "text-muted-foreground hover:text-foreground"
    )}
  >
    <Icon size={14} className={active ? "text-accent-dark" : ""} />
    {label}
  </button>
)
