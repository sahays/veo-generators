import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  FileText, Code, History, Plus, CheckCircle2, 
  Copy, Zap, Loader2, MoreVertical, ExternalLink, Eye 
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { api } from '@/lib/api'
import { ResourceModal } from '@/components/ads/ResourceModal'
import type { SystemResource } from '@/types/project'

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

  const filteredResources = resources.filter(r => r.type === activeTab)

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

  const handleActivate = async (id: string) => {
    try {
      await api.system.activateResource(id)
      fetchResources()
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="space-y-8">
      {/* Header Area */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
        <div className="space-y-1">
          <h2 className="text-xl font-heading font-bold tracking-tight text-foreground">System Engine</h2>
          <p className="text-xs text-muted-foreground max-w-lg">
            Manage the core logic of the video generation pipeline through versioned prompts and schemas.
          </p>
        </div>
        <div className="flex bg-muted/50 p-1 rounded-xl border border-border">
          <TabButton 
            active={activeTab === 'prompt'} 
            onClick={() => setActiveTab('prompt')}
            icon={FileText}
            label="System Prompts"
          />
          <TabButton 
            active={activeTab === 'schema'} 
            onClick={() => setActiveTab('schema')}
            icon={Code}
            label="Response Schemas"
          />
        </div>
      </div>

      {/* Grid of Cards */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <Loader2 className="animate-spin text-accent" size={32} />
          <p className="text-xs font-medium text-muted-foreground animate-pulse">Synchronizing with Firestore...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Create New Placeholder Card */}
          <motion.button
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.99 }}
            onClick={handleCreateNew}
            className="flex flex-col items-center justify-center gap-3 p-8 border-2 border-dashed border-border rounded-2xl hover:border-accent/40 hover:bg-accent/5 transition-all group"
          >
            <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center text-muted-foreground group-hover:bg-accent group-hover:text-slate-900 transition-colors">
              <Plus size={24} />
            </div>
            <div className="text-center">
              <p className="text-sm font-bold text-foreground">Create New {activeTab === 'prompt' ? 'Prompt' : 'Schema'}</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">Start from a blank slate</p>
            </div>
          </motion.button>

          {filteredResources.map((res) => (
            <ResourceCard 
              key={res.id} 
              resource={res} 
              onIterate={() => handleIterate(res)}
              onView={() => handleView(res)}
              onActivate={() => handleActivate(res.id)}
              allVersions={resources.filter(r => r.category === res.category && r.type === res.type)}
            />
          ))}
        </div>
      )}

      {/* Modal */}
      <ResourceModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchResources}
        type={activeTab}
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

const ResourceCard = ({ resource, onIterate, onActivate, onView }: any) => {
  return (
    <Card className="p-0 overflow-hidden group">
      <div className="p-6 space-y-4">
        <div className="flex items-start justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <h4 className="text-base font-bold text-foreground line-clamp-1">{resource.name}</h4>
              {resource.is_active && (
                <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-500 text-[8px] font-bold uppercase tracking-wider">
                  <CheckCircle2 size={8} /> Active
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 text-[10px] text-muted-foreground font-mono">
              <span className="bg-muted px-1.5 py-0.5 rounded">v{resource.version}</span>
              <span className="bg-muted px-1.5 py-0.5 rounded capitalize">{resource.category}</span>
            </div>
          </div>
          <div className="flex gap-1">
            <button 
              onClick={onView}
              className="p-1 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
              title="View Content"
            >
              <Eye size={16} />
            </button>
            <button className="p-1 rounded-lg hover:bg-muted text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
              <MoreVertical size={16} />
            </button>
          </div>
        </div>

        <div className="relative aspect-[4/1.5] w-full rounded-xl bg-muted/50 border border-border/50 overflow-hidden">
          <pre className="p-3 font-mono text-[9px] text-muted-foreground leading-relaxed overflow-hidden">
            {resource.content}
          </pre>
          <div className="absolute inset-0 bg-gradient-to-t from-card/80 to-transparent" />
        </div>

        <div className="flex items-center justify-between pt-2">
          <p className="text-[9px] text-muted-foreground">
            Created {new Date(resource.createdAt).toLocaleDateString()}
          </p>
          <div className="flex gap-2">
            {!resource.is_active && (
              <Button variant="ghost" className="h-7 px-2 text-[10px]" onClick={onActivate}>
                Activate
              </Button>
            )}
            <Button variant="secondary" className="h-7 px-2 text-[10px]" icon={Copy} onClick={onIterate}>
              Iterate
            </Button>
          </div>
        </div>
      </div>
    </Card>
  )
}

