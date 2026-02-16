import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  FileText, Code, History, Plus, CheckCircle2, 
  Copy, ArrowRight, Zap, Info, Loader2 
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button, Card } from '@/components/Common'
import { api } from '@/lib/api'
import type { SystemResource } from '@/types/project'

export const PromptsPage = () => {
  const [resources, setResources] = useState<SystemResource[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [isEditing, setIsEditing] = useState(false)
  const [isNew, setIsNew] = useState(false)
  const [editData, setEditData] = useState({ name: '', content: '', type: 'prompt' as 'prompt' | 'schema', category: 'project-analysis' })

  const fetchResources = async () => {
    setLoading(true)
    try {
      const data = await api.system.listResources()
      setResources(data)
      if (data.length > 0 && !selectedId) {
        setSelectedId(data[0].id)
      }
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchResources()
  }, [])

  const selectedResource = resources.find(r => r.id === selectedId)

  const handleCreateNew = (type: 'prompt' | 'schema') => {
    setEditData({
      name: `New ${type === 'prompt' ? 'Prompt' : 'Schema'}`,
      content: '',
      type,
      category: 'project-analysis'
    })
    setIsNew(true)
    setIsEditing(true)
    setSelectedId(null)
  }

  const handleCopyToNew = () => {
    if (!selectedResource) return
    setEditData({
      name: `${selectedResource.name} (Copy)`,
      content: selectedResource.content,
      type: selectedResource.type,
      category: selectedResource.category
    })
    setIsNew(false)
    setIsEditing(true)
  }

  const handleSave = async () => {
    try {
      const currentCategoryResources = resources.filter(r => r.category === editData.category && r.type === editData.type)
      const nextVersion = currentCategoryResources.length > 0 
        ? Math.max(...currentCategoryResources.map(r => r.version)) + 1 
        : 1

      const newResource = {
        type: editData.type,
        category: editData.category,
        name: editData.name,
        content: editData.content,
        version: nextVersion,
        is_active: currentCategoryResources.length === 0, // Make active if it's the first
        createdAt: new Date().toISOString()
      }
      const saved = await api.system.createResource(newResource)
      setIsEditing(false)
      setIsNew(false)
      setSelectedId(saved.id)
      fetchResources()
    } catch (err) {
      console.error(err)
    }
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
    <div className="flex h-full gap-6">
      {/* Sidebar List */}
      <div className="w-80 flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-heading font-bold">System Resources</h2>
          <div className="flex gap-1">
            <Button className="px-1.5 py-1" onClick={() => handleCreateNew('prompt')} title="New Prompt"><FileText size={14}/></Button>
            <Button className="px-1.5 py-1" onClick={() => handleCreateNew('schema')} title="New Schema"><Code size={14}/></Button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto space-y-2 pr-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="animate-spin text-muted-foreground" />
            </div>
          ) : (
            <>
              <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground px-2 pt-2">Prompts</div>
              {resources.filter(r => r.type === 'prompt').map(res => (
                <ResourceItem 
                  key={res.id} 
                  resource={res} 
                  isSelected={selectedId === res.id} 
                  onSelect={() => { setSelectedId(res.id); setIsEditing(false); }} 
                />
              ))}
              
              <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground px-2 pt-6">Schemas</div>
              {resources.filter(r => r.type === 'schema').map(res => (
                <ResourceItem 
                  key={res.id} 
                  resource={res} 
                  isSelected={selectedId === res.id} 
                  onSelect={() => { setSelectedId(res.id); setIsEditing(false); }} 
                />
              ))}
            </>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        <AnimatePresence mode="wait">
          {(selectedResource || isNew) ? (
            <motion.div
              key={(isNew ? 'new' : selectedId) + (isEditing ? '-edit' : '-view')}
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -10 }}
              className="flex-1 flex flex-col gap-4"
            >
              <Card className="flex-1 flex flex-col p-0 overflow-hidden">
                <div className="px-6 py-4 border-b border-border flex items-center justify-between bg-muted/30">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-accent text-slate-900">
                      {(isNew ? editData.type : selectedResource?.type) === 'prompt' ? <FileText size={18} /> : <Code size={18} />}
                    </div>
                    <div>
                      <h3 className="text-base font-bold">
                        {isEditing ? (
                          <input 
                            value={editData.name} 
                            onChange={e => setEditData({...editData, name: e.target.value})}
                            className="bg-transparent border-b border-accent focus:outline-none w-64"
                            placeholder="Resource Name"
                          />
                        ) : selectedResource?.name}
                      </h3>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-[10px] text-muted-foreground uppercase font-bold tracking-tighter bg-muted px-1.5 py-0.5 rounded">
                          {isEditing ? 'New Version' : `v${selectedResource?.version}`}
                        </span>
                        {isEditing ? (
                          <div className="relative group">
                            <input 
                              value={editData.category} 
                              onChange={e => setEditData({...editData, category: e.target.value})}
                              className={cn(
                                "text-[10px] uppercase font-bold tracking-tighter bg-muted px-1.5 py-0.5 rounded focus:outline-none focus:ring-1 focus:ring-accent w-32",
                                !editData.category && "ring-1 ring-red-500"
                              )}
                              placeholder="category"
                            />
                            {!editData.category && (
                              <span className="absolute left-0 -bottom-5 text-[8px] text-red-500 whitespace-nowrap">Category required</span>
                            )}
                            <div className="absolute left-0 -bottom-8 hidden group-hover:block z-10 bg-black/90 text-white text-[9px] p-1.5 rounded whitespace-nowrap">
                              Suggested: project-analysis
                            </div>
                          </div>
                        ) : (
                          <span className="text-[10px] text-muted-foreground uppercase font-bold tracking-tighter bg-muted px-1.5 py-0.5 rounded">
                            {selectedResource?.category}
                          </span>
                        )}
                        {!isEditing && selectedResource?.is_active && (
                          <span className="text-[10px] text-emerald-500 uppercase font-bold tracking-tighter bg-emerald-500/10 px-1.5 py-0.5 rounded flex items-center gap-1">
                            <CheckCircle2 size={8} /> Active
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {isEditing ? (
                      <>
                        <Button variant="ghost" className="h-8 px-3 text-xs" onClick={() => { setIsEditing(false); setIsNew(false); }}>Cancel</Button>
                        <Button className="h-8 px-3 text-xs" icon={Zap} onClick={handleSave}>Save Resource</Button>
                      </>
                    ) : (
                      <>
                        {selectedResource && !selectedResource.is_active && (
                          <Button variant="ghost" className="h-8 px-3 text-xs" icon={CheckCircle2} onClick={() => handleActivate(selectedResource.id)}>Set Active</Button>
                        )}
                        <Button className="h-8 px-3 text-xs" icon={Copy} onClick={handleCopyToNew}>Copy to New</Button>
                      </>
                    )}
                  </div>
                </div>

                <div className="flex-1 relative">
                  {isEditing ? (
                    <textarea
                      value={editData.content}
                      onChange={e => setEditData({...editData, content: e.target.value})}
                      className="absolute inset-0 w-full h-full p-6 font-mono text-sm bg-transparent outline-none resize-none"
                      placeholder={editData.type === 'prompt' ? "Enter your prompt template here..." : "Enter your JSON schema here..."}
                      spellCheck={false}
                    />
                  ) : (
                    <pre className="absolute inset-0 w-full h-full p-6 font-mono text-xs overflow-auto whitespace-pre-wrap select-text">
                      {selectedResource?.content}
                    </pre>
                  )}
                </div>
              </Card>

              {/* Version History (Quick view) */}
              {!isEditing && selectedResource && (
                <div className="h-48 flex flex-col gap-2">
                  <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                    <History size={12} /> Version History for {selectedResource.category}
                  </div>
                  <div className="flex-1 flex gap-3 overflow-x-auto pb-2 no-scrollbar">
                    {resources
                      .filter(r => r.category === selectedResource.category && r.type === selectedResource.type)
                      .sort((a, b) => b.version - a.version)
                      .map(ver => (
                        <button
                          key={ver.id}
                          onClick={() => setSelectedId(ver.id)}
                          className={cn(
                            "w-48 shrink-0 glass p-3 rounded-lg border text-left flex flex-col justify-between transition-all",
                            selectedId === ver.id ? "border-accent bg-accent/5 ring-1 ring-accent" : "border-border hover:border-accent/40"
                          )}
                        >
                          <div>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-[10px] font-bold">v{ver.version}</span>
                              {ver.is_active && <CheckCircle2 size={10} className="text-emerald-500" />}
                            </div>
                            <p className="text-[11px] font-medium line-clamp-1">{ver.name}</p>
                          </div>
                          <p className="text-[8px] text-muted-foreground mt-2">
                            {new Date(ver.createdAt).toLocaleDateString()}
                          </p>
                        </button>
                      ))}
                  </div>
                </div>
              )}
            </motion.div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground italic">
              Select a resource to view details
            </div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

const ResourceItem = ({ resource, isSelected, onSelect }: { resource: SystemResource, isSelected: boolean, onSelect: () => void }) => {
  return (
    <button
      onClick={onSelect}
      className={cn(
        "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl transition-all border",
        isSelected 
          ? "bg-accent/10 border-accent text-accent-dark shadow-sm" 
          : "border-transparent text-muted-foreground hover:bg-muted/50"
      )}
    >
      <div className={cn(
        "p-1.5 rounded-lg",
        isSelected ? "bg-accent text-slate-900" : "bg-muted"
      )}>
        {resource.type === 'prompt' ? <FileText size={14} /> : <Code size={14} />}
      </div>
      <div className="flex-1 min-w-0 text-left">
        <p className="text-xs font-bold truncate">{resource.name}</p>
        <div className="flex items-center gap-1.5 mt-0.5">
          <span className="text-[8px] font-mono opacity-60">v{resource.version}</span>
          {resource.is_active && (
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.5)]" />
          )}
        </div>
      </div>
      {isSelected && <ArrowRight size={14} className="opacity-40" />}
    </button>
  )
}
