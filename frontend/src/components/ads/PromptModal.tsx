import { useState } from 'react'
import { ImageIcon, Video, Copy, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Modal } from '@/components/Modal'
import type { Scene } from '@/types/project'

export const PromptModal = ({
  scene,
  onClose,
}: {
  scene: Scene
  onClose: () => void
}) => {
  const [activeTab, setActiveTab] = useState<'image' | 'video'>('image')
  const [copied, setCopied] = useState(false)

  const imagePrompt = scene.image_prompt
  const videoPrompt = scene.video_prompt
  const currentPrompt = activeTab === 'image' ? imagePrompt : videoPrompt

  const handleCopy = () => {
    if (!currentPrompt) return
    navigator.clipboard.writeText(currentPrompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <Modal
      isOpen={true}
      onClose={onClose}
      title="Generated Prompts"
      subtitle="The enriched prompt sent to the AI model."
      maxWidth="max-w-lg"
    >
      <div className="-mx-6 -mt-6">
        <div className="flex border-b border-border">
          <button
            onClick={() => setActiveTab('image')}
            className={cn(
              "flex-1 px-4 py-3 text-xs font-bold uppercase tracking-wider transition-colors",
              activeTab === 'image'
                ? "text-accent-dark border-b-2 border-accent bg-accent/5"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            )}
          >
            <span className="flex items-center justify-center gap-1.5">
              <ImageIcon size={12} /> Image Prompt
            </span>
          </button>
          <button
            onClick={() => setActiveTab('video')}
            className={cn(
              "flex-1 px-4 py-3 text-xs font-bold uppercase tracking-wider transition-colors",
              activeTab === 'video'
                ? "text-accent-dark border-b-2 border-accent bg-accent/5"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
            )}
          >
            <span className="flex items-center justify-center gap-1.5">
              <Video size={12} /> Video Prompt
            </span>
          </button>
        </div>

        <div className="p-6">
          {currentPrompt ? (
            <div className="relative group">
              <pre className="text-sm leading-relaxed text-foreground bg-background rounded-xl p-4 whitespace-pre-wrap break-words max-h-72 overflow-y-auto border border-border">
                {currentPrompt}
              </pre>
              <button
                onClick={handleCopy}
                className={cn(
                  "absolute top-3 right-3 p-1.5 rounded-lg border transition-all",
                  copied
                    ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-500"
                    : "bg-background border-border text-muted-foreground hover:text-foreground hover:border-accent/50 opacity-0 group-hover:opacity-100"
                )}
                title="Copy to clipboard"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </div>
          ) : (
            <div className="text-center py-10 rounded-xl border border-dashed border-border bg-muted/30">
              <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center mx-auto mb-3">
                {activeTab === 'image' ? <ImageIcon size={18} className="text-muted-foreground" /> : <Video size={18} className="text-muted-foreground" />}
              </div>
              <p className="text-sm font-medium text-foreground">Not generated yet</p>
              <p className="text-xs text-muted-foreground mt-1">
                Generate a {activeTab === 'image' ? 'frame' : 'video'} first to see its prompt.
              </p>
            </div>
          )}
        </div>
      </div>
    </Modal>
  )
}
