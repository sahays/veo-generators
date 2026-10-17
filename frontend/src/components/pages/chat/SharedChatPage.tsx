import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Bot, User, Clock, Copy, Check, ArrowLeft, Share2 } from 'lucide-react'
import { clsx } from 'clsx'
import { Button } from '@/components/ui/button'
import { api } from '@/hooks/useApiClient'
import type { SharedChatRecord } from '@/lib/api'
import {
  AGENT_LABELS,
  ChatMarkdownBody,
  formatLatency,
} from '@/components/chat/ChatWindow'

const SharedChatBanner = ({
  record,
  linkCopied,
  onCopyLink,
  onOpenChat,
}: {
  record: SharedChatRecord | null
  linkCopied: boolean
  onCopyLink: () => void
  onOpenChat: () => void
}) => (
  <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/95 backdrop-blur px-6 py-4 dark:border-slate-800 dark:bg-slate-900/95">
    <div className="mx-auto flex max-w-4xl items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-orange-600 text-white shadow-sm">
          <Bot size={22} />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-base font-bold text-slate-900 dark:text-white">
            {record?.title || 'Shared Ask Aanya Conversation'}
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Public read-only snapshot · Ask Aanya Multi-Agent System
            {record?.created_at ? ` · ${new Date(record.created_at).toLocaleString()}` : ''}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button type="button" variant="outline" size="sm" onClick={onCopyLink}>
          {linkCopied ? <Check size={14} /> : <Share2 size={14} />}
          <span>{linkCopied ? 'Link Copied' : 'Copy Link'}</span>
        </Button>
        <Button type="button" variant="primary" size="sm" onClick={onOpenChat}>
          <ArrowLeft size={14} />
          <span>Open Ask Aanya</span>
        </Button>
      </div>
    </div>
  </header>
)

const SharedChatMessageBubble = ({
  msg,
  isCopied,
  onCopy,
}: {
  msg: NonNullable<SharedChatRecord['messages']>[number]
  isCopied: boolean
  onCopy: () => void
}) => {
  const latencyLabel = formatLatency(msg.latency_ms)
  return (
    <div className={clsx('flex w-full flex-col', msg.role === 'user' ? 'items-end' : 'items-start')}>
      <div className="flex max-w-[95%] items-end gap-2 md:max-w-[85%]">
        {msg.role === 'model' && (
          <div className="mb-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-orange-600 text-white shadow-sm">
            <Bot size={14} />
          </div>
        )}
        <div
          className={clsx(
            'min-w-0 overflow-hidden rounded-2xl px-4 py-2.5 text-sm shadow-sm',
            msg.role === 'user'
              ? 'bg-orange-600 text-white rounded-br-none'
              : 'bg-white text-slate-900 border border-slate-200 rounded-bl-none dark:bg-slate-800 dark:text-white dark:border-slate-700',
          )}
        >
          {msg.role === 'user' ? (
            <div className="whitespace-pre-wrap">{msg.content}</div>
          ) : (
            <ChatMarkdownBody content={msg.content} />
          )}
          {msg.role === 'model' && (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-1.5 text-[10px] text-slate-500 dark:border-slate-700/80 dark:text-slate-400">
              <div className="flex flex-wrap items-center gap-2">
                {msg.agent && (
                  <span className="font-semibold uppercase tracking-wider">
                    {AGENT_LABELS[msg.agent] || `${msg.agent} Agent`}
                  </span>
                )}
                {latencyLabel && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-700/70 dark:text-slate-300">
                    <Clock size={10} />
                    {latencyLabel}
                  </span>
                )}
              </div>
              <Button
                type="button"
                variant="unstyled"
                onClick={onCopy}
                className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200"
              >
                {isCopied ? <Check size={12} /> : <Copy size={12} />}
                <span>{isCopied ? 'Copied' : 'Copy'}</span>
              </Button>
            </div>
          )}
        </div>
        {msg.role === 'user' && (
          <div className="mb-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
            <User size={14} />
          </div>
        )}
      </div>
    </div>
  )
}

const SharedChatMessagesMain = ({
  loading,
  error,
  record,
  copiedIndex,
  onCopy,
}: {
  loading: boolean
  error: string | null
  record: SharedChatRecord | null
  copiedIndex: number | null
  onCopy: (text: string, index: number) => void
}) => (
  <main className="mx-auto w-full max-w-4xl flex-1 p-6 space-y-4">
    {loading && <div className="flex items-center justify-center py-20 text-sm text-slate-500">Loading shared conversation...</div>}
    {error && !loading && (
      <div className="rounded-2xl border border-rose-200 bg-white p-8 text-center dark:border-rose-900/50 dark:bg-slate-900">
        <p className="text-sm font-medium text-rose-600 dark:text-rose-400">{error}</p>
      </div>
    )}
    {record?.messages?.map((msg, i) => (
      <SharedChatMessageBubble key={i} msg={msg} isCopied={copiedIndex === i} onCopy={() => onCopy(msg.content, i)} />
    ))}
  </main>
)

export const SharedChatPage: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [record, setRecord] = useState<SharedChatRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null)
  const [linkCopied, setLinkCopied] = useState(false)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    api.chat.getSharedChat(id).then((res) => { setRecord(res); setError(null) }).catch((err: unknown) => setError(err instanceof Error ? err.message : 'Shared conversation not found')).finally(() => setLoading(false))
  }, [id])

  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedIndex(index)
      setTimeout(() => setCopiedIndex((p) => (p === index ? null : p)), 2000)
    } catch { /* ignore */ }
  }
  const handleCopyLink = async () => {
    await navigator.clipboard.writeText(window.location.href)
    setLinkCopied(true); setTimeout(() => setLinkCopied(false), 2000)
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex flex-col">
      <SharedChatBanner record={record} linkCopied={linkCopied} onCopyLink={handleCopyLink} onOpenChat={() => navigate('/chat')} />
      <SharedChatMessagesMain loading={loading} error={error} record={record} copiedIndex={copiedIndex} onCopy={handleCopy} />
    </div>
  )
}

