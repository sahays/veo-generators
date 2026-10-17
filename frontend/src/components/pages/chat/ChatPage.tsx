import React from 'react'
import { Bot, Sparkles, Maximize2, Minimize2 } from 'lucide-react'
import { clsx } from 'clsx'
import { Button } from '@/components/ui/button'
import { ChatWindow } from '@/components/chat/ChatWindow'
import { useChatStore } from '@/store/useChatStore'

const ChatHeader = ({
  isFullscreen,
  onToggleFullscreen,
}: {
  isFullscreen: boolean
  onToggleFullscreen: () => void
}) => (
  <div className="flex items-center justify-between border-b border-border bg-muted/30 px-6 py-3.5">
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-[6px] btn-primary text-white shadow-lg shadow-accent/20">
        <Bot size={24} />
      </div>
      <div>
        <h2 className="text-lg font-heading font-bold text-foreground">Ask Aanya</h2>
        <div className="flex items-center gap-1.5">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            9-Agent Gemini ADK System Online
          </p>
        </div>
      </div>
    </div>
    <div className="flex items-center gap-2">
      <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full bg-background border border-border shadow-sm">
        <Sparkles size={14} className="text-amber-500" />
        <span className="text-xs font-medium text-muted-foreground">
          Powered by Gemini ADK (3.5 Flash-Lite + 3.8 Flash)
        </span>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onToggleFullscreen}
        title={isFullscreen ? 'Exit full screen' : 'Expand to full vertical body area'}
        className="h-8 gap-1.5 text-xs"
      >
        {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
        <span className="hidden sm:inline">
          {isFullscreen ? 'Exit Full Screen' : 'Full Screen'}
        </span>
      </Button>
    </div>
  </div>
)

export const ChatPage: React.FC = () => {
  const { isFullscreen, setIsFullscreen } = useChatStore()

  return (
    <div
      className={clsx(
        'flex flex-col overflow-hidden bg-card',
        isFullscreen
          ? 'h-screen w-full rounded-none border-0'
          : 'h-[calc(100vh-120px)] rounded-2xl border border-border shadow-sm',
      )}
    >
      <ChatHeader isFullscreen={isFullscreen} onToggleFullscreen={() => setIsFullscreen(!isFullscreen)} />
      <div className="flex-1 overflow-hidden">
        <ChatWindow />
      </div>
    </div>
  )
}
