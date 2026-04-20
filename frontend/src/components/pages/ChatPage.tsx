import React from 'react'
import { Bot, Sparkles } from 'lucide-react'
import { ChatWindow } from '@/components/chat/ChatWindow'

export const ChatPage: React.FC = () => {
  return (
    <div className="flex flex-col h-[calc(100vh-120px)] overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      {/* Page Header */}
      <div className="flex items-center justify-between border-b border-border bg-muted/30 px-6 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-white shadow-lg shadow-accent/20">
            <Bot size={24} />
          </div>
          <div>
            <h2 className="text-lg font-heading font-bold text-foreground">Ask Aanya</h2>
            <div className="flex items-center gap-1.5">
              <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              <p className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Multi-Agent System Online</p>
            </div>
          </div>
        </div>
        <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full bg-background border border-border shadow-sm">
          <Sparkles size={14} className="text-amber-500" />
          <span className="text-xs font-medium text-muted-foreground">Powered by Gemini 3.1</span>
        </div>
      </div>

      {/* Main Chat Interface */}
      <div className="flex-1 overflow-hidden">
        <ChatWindow />
      </div>
    </div>
  )
}
