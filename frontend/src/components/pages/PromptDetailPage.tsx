import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, Copy, Check, Loader2, FileText } from 'lucide-react'
import { Button } from '@/components/Common'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { SystemResource } from '@/types/project'

const CATEGORY_LABELS: Record<string, string> = {
  'production-movie': 'Movie Production',
  'production-ad': 'Ad Production',
  'production-social': 'Social Production',
  'key-moments': 'Key Moments Analysis',
  'thumbnails': 'Thumbnail Analysis',
  'collage': 'Thumbnail Collage',
  'orientation': 'Orientation / Reframe',
  'promo': 'Promo Generation',
}

export const PromptDetailPage = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [resource, setResource] = useState<SystemResource | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    api.system.getResource(id)
      .then(setResource)
      .catch(() => setError('Prompt not found'))
      .finally(() => setLoading(false))
  }, [id])

  const handleCopy = async () => {
    if (!resource) return
    await navigator.clipboard.writeText(resource.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <Loader2 className="animate-spin text-accent" size={32} />
        <p className="text-xs font-medium text-muted-foreground animate-pulse">Loading prompt...</p>
      </div>
    )
  }

  if (error || !resource) {
    return (
      <div className="flex flex-col items-center justify-center py-24 gap-4">
        <FileText className="text-muted-foreground/30" size={40} />
        <p className="text-sm text-muted-foreground">{error || 'Prompt not found'}</p>
        <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/prompts')}>
          Back to Prompts
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Back nav */}
      <button
        onClick={() => navigate('/prompts')}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft size={14} />
        All Prompts
      </button>

      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        className="space-y-4"
      >
        <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
          <div className="space-y-2">
            <h2 className="text-xl font-heading font-bold tracking-tight text-foreground">
              {resource.name}
            </h2>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="bg-muted px-2 py-0.5 rounded text-[10px] font-mono text-muted-foreground capitalize">
                {CATEGORY_LABELS[resource.category] || resource.category}
              </span>
              <span className="bg-muted px-2 py-0.5 rounded text-[10px] font-mono text-muted-foreground">
                v{resource.version}
              </span>
              {resource.is_active && (
                <span className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-2 py-0.5 rounded text-[10px] font-mono font-medium">
                  Active
                </span>
              )}
              <span className="text-[10px] text-muted-foreground">
                {new Date(resource.createdAt).toLocaleDateString(undefined, {
                  year: 'numeric', month: 'short', day: 'numeric'
                })}
              </span>
            </div>
          </div>
          <Button
            variant="ghost"
            icon={copied ? Check : Copy}
            onClick={handleCopy}
            className={cn(copied && 'text-emerald-500')}
          >
            {copied ? 'Copied' : 'Copy Content'}
          </Button>
        </div>

        {/* Content */}
        <div className="relative border border-border rounded-xl overflow-hidden bg-muted/20">
          <div className="absolute top-3 right-3 z-10">
            <span className="px-2 py-1 rounded bg-muted text-[10px] font-mono text-accent-dark font-medium border border-border">
              TEXT
            </span>
          </div>
          <pre className="p-6 font-mono text-xs text-foreground/80 leading-relaxed overflow-x-auto whitespace-pre-wrap">
            {resource.content}
          </pre>
        </div>
      </motion.div>
    </div>
  )
}
