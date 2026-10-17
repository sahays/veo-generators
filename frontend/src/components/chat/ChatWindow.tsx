import React, { useState, useRef, useEffect } from 'react'
import { Send, Bot, Loader2, Trash2, Clock, Share2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useChatStore, type Message } from '@/store/useChatStore'
import { shareChatTranscript } from './widgets/useChatWidgetActions'
import {
  AGENT_LABELS,
  formatChatMarkdown,
  formatLatency,
  ChatMarkdownBody,
  SharedLinkBanner,
  ChatEmptyState,
  ChatMessageRow,
} from './widgets/ChatMessageParts'

export { AGENT_LABELS, formatChatMarkdown, formatLatency, ChatMarkdownBody }

interface ChatWindowProps {
  showClearHistory?: boolean
}

const ChatTypingIndicator: React.FC<{ elapsedMs: number }> = ({ elapsedMs }) => (
  <div className="flex items-start gap-2">
    <div className="flex h-6 w-6 items-center justify-center rounded-md bg-orange-600 text-white">
      <Bot size={14} />
    </div>
    <div className="flex items-center gap-2 rounded-2xl bg-white px-4 py-3 border border-slate-200 shadow-sm dark:bg-slate-800 dark:border-slate-700">
      <Loader2 size={16} className="animate-spin text-orange-500" />
      <span className="text-xs text-slate-500">Thinking...</span>
      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-mono text-[10px] text-slate-500 dark:bg-slate-700 dark:text-slate-300">
        <Clock size={10} />
        {(elapsedMs / 1000).toFixed(1)}s
      </span>
    </div>
  </div>
)

const ChatInputForm: React.FC<{
  inputValue: string
  isTyping: boolean
  showClearHistory: boolean
  hasMessages: boolean
  sharingAll: boolean
  sharingDisabled: boolean
  onInputChange: (v: string) => void
  onSubmit: (e: React.FormEvent) => void
  onClear: () => void
  onShareAll: () => void
}> = ({
  inputValue,
  isTyping,
  showClearHistory,
  hasMessages,
  sharingAll,
  sharingDisabled,
  onInputChange,
  onSubmit,
  onClear,
  onShareAll,
}) => (
  <div className="border-t border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
    <form onSubmit={onSubmit} className="max-w-4xl mx-auto flex items-center gap-2">
      {showClearHistory && hasMessages && (
        <>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClear}
            title="Clear chat history"
            className="h-10 shrink-0 text-slate-500 hover:text-red-500 hover:border-red-200"
          >
            <Trash2 size={15} />
            <span className="hidden sm:inline text-xs">Clear</span>
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={sharingDisabled}
            onClick={onShareAll}
            title="Share full chat to public link"
            className="h-10 shrink-0 text-slate-600 dark:text-slate-300"
          >
            <Share2 size={15} />
            <span className="hidden sm:inline text-xs">
              {sharingAll ? 'Sharing...' : 'Share chat'}
            </span>
          </Button>
        </>
      )}
      <Input
        type="text"
        value={inputValue}
        onChange={(e) => onInputChange(e.target.value)}
        placeholder="Ask Aanya or any of her 8 feature specialists..."
        className="flex-1 h-10"
      />
      <Button
        type="submit"
        size="icon"
        disabled={!inputValue.trim() || isTyping}
        className="h-10 w-10 shrink-0"
      >
        <Send size={16} />
      </Button>
    </form>
  </div>
)

function useTypingElapsed(isTyping: boolean): number {
  const [elapsedMs, setElapsedMs] = useState(0)
  useEffect(() => {
    if (!isTyping) {
      setElapsedMs(0)
      return
    }
    const started = Date.now()
    const timer = setInterval(() => setElapsedMs(Date.now() - started), 100)
    return () => clearInterval(timer)
  }, [isTyping])
  return elapsedMs
}

function useChatShareState() {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [sharingIndex, setSharingIndex] = useState<number | 'all' | null>(null)
  const [sharedUrl, setSharedUrl] = useState<string | null>(null)
  const [sharedCopied, setSharedCopied] = useState(false)

  const handleCopyMessage = async (text: string, index: number) => {
    await navigator.clipboard.writeText(text).catch(() => {})
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex((prev) => (prev === index ? null : prev)), 2000)
  }

  const handleShareMessages = async (subset: Message[], tag: number | 'all') => {
    if (!subset.length || sharingIndex !== null) return
    setSharingIndex(tag)
    try {
      const url = await shareChatTranscript(subset)
      setSharedUrl(url)
      await navigator.clipboard.writeText(url).then(() => setSharedCopied(true)).catch(() => setSharedCopied(false))
      setTimeout(() => setSharedCopied(false), 2500)
    } finally {
      setSharingIndex(null)
    }
  }

  return { copiedIndex, sharingIndex, sharedUrl, sharedCopied, setSharedUrl, setSharedCopied, handleCopyMessage, handleShareMessages }
}

const ChatTranscriptStream: React.FC<{
  scrollRef: React.RefObject<HTMLDivElement>
  messages: Message[]
  isTyping: boolean
  elapsedMs: number
  copiedIndex: number | null
  sharingDisabled: boolean
  sendMessage: (text: string) => void
  onCopy: (text: string, index: number) => void
  onSharePair: (subset: Message[], tag: number) => void
  onFeedback: (index: number, fb: 'up' | 'down' | undefined) => void
  addSystemMessage: (content: string, data?: Record<string, unknown>) => void
}> = ({
  scrollRef,
  messages,
  isTyping,
  elapsedMs,
  copiedIndex,
  sharingDisabled,
  sendMessage,
  onCopy,
  onSharePair,
  onFeedback,
  addSystemMessage,
}) => (
  <div ref={scrollRef} className="flex-1 overflow-y-auto bg-slate-50 p-4 space-y-4 scrollbar-thin dark:bg-slate-950">
    {messages.length === 0 && <ChatEmptyState onSelectPrompt={sendMessage} />}
    {messages.map((msg, i) => (
      <ChatMessageRow
        key={i}
        msg={msg}
        index={i}
        isCopied={copiedIndex === i}
        sharingDisabled={sharingDisabled}
        sendMessage={sendMessage}
        onCopy={onCopy}
        onShare={() => onSharePair(i > 0 && messages[i - 1]?.role === 'user' ? [messages[i - 1], msg] : [msg], i)}
        onFeedback={onFeedback}
        onConfirmed={(jobType, result, title) =>
          addSystemMessage('Job created successfully!', {
            job_id: result.id || result.turn_id,
            job_type: jobType,
            status: result.status || 'pending',
            title: result.name || result.display_name || title,
          })
        }
        onFailed={(err) => addSystemMessage(`Failed to create job: ${err}`)}
      />
    ))}
    {isTyping && <ChatTypingIndicator elapsedMs={elapsedMs} />}
  </div>
)

const ChatWindowLayout: React.FC<{
  scrollRef: React.RefObject<HTMLDivElement>
  messages: Message[]
  isTyping: boolean
  elapsedMs: number
  inputValue: string
  showClearHistory: boolean
  share: ReturnType<typeof useChatShareState>
  sendMessage: (text: string) => void
  setMessageFeedback: (index: number, fb: 'up' | 'down' | undefined) => void
  addSystemMessage: (content: string, data?: Record<string, unknown>) => void
  clearHistory: () => void
  onInputChange: (v: string) => void
  onSubmit: (e: React.FormEvent) => void
}> = ({
  scrollRef,
  messages,
  isTyping,
  elapsedMs,
  inputValue,
  showClearHistory,
  share,
  sendMessage,
  setMessageFeedback,
  addSystemMessage,
  clearHistory,
  onInputChange,
  onSubmit,
}) => (
  <div className="flex flex-col h-full bg-white dark:bg-slate-900">
    {share.sharedUrl && (
      <SharedLinkBanner
        sharedUrl={share.sharedUrl}
        sharedCopied={share.sharedCopied}
        onCopy={async () => {
          await navigator.clipboard.writeText(share.sharedUrl || '')
          share.setSharedCopied(true)
          setTimeout(() => share.setSharedCopied(false), 2000)
        }}
        onDismiss={() => share.setSharedUrl(null)}
      />
    )}
    <ChatTranscriptStream
      scrollRef={scrollRef}
      messages={messages}
      isTyping={isTyping}
      elapsedMs={elapsedMs}
      copiedIndex={share.copiedIndex}
      sharingDisabled={share.sharingIndex !== null}
      sendMessage={sendMessage}
      onCopy={share.handleCopyMessage}
      onSharePair={share.handleShareMessages}
      onFeedback={setMessageFeedback}
      addSystemMessage={addSystemMessage}
    />
    <ChatInputForm
      inputValue={inputValue}
      isTyping={isTyping}
      showClearHistory={showClearHistory}
      hasMessages={messages.length > 0}
      sharingAll={share.sharingIndex === 'all'}
      sharingDisabled={share.sharingIndex !== null}
      onInputChange={onInputChange}
      onSubmit={onSubmit}
      onClear={clearHistory}
      onShareAll={() => share.handleShareMessages(messages, 'all')}
    />
  </div>
)

export const ChatWindow: React.FC<ChatWindowProps> = ({ showClearHistory = true }) => {
  const { messages, sendMessage, isTyping, clearHistory, addSystemMessage, setMessageFeedback } = useChatStore()
  const [inputValue, setInputValue] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const elapsedMs = useTypingElapsed(isTyping)
  const share = useChatShareState()

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [messages, isTyping, share.sharedUrl])

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inputValue.trim() || isTyping) return
    const text = inputValue.trim()
    setInputValue('')
    await sendMessage(text)
  }

  return (
    <ChatWindowLayout
      scrollRef={scrollRef} messages={messages} isTyping={isTyping} elapsedMs={elapsedMs}
      inputValue={inputValue} showClearHistory={showClearHistory} share={share}
      sendMessage={sendMessage} setMessageFeedback={setMessageFeedback}
      addSystemMessage={addSystemMessage} clearHistory={clearHistory}
      onInputChange={setInputValue} onSubmit={handleSend}
    />
  )
}
