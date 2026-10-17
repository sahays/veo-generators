import React from 'react'
import {
  Bot,
  User,
  Sparkles,
  Clock,
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
  Share2,
  ExternalLink,
} from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { clsx } from 'clsx'
import { Button } from '@/components/ui/button'
import type { Message } from '@/store/useChatStore'
import {
  VideoResultCard,
  VideoSourcePicker,
  ImageSourcePicker,
  PromptPicker,
  ConfirmationCard,
  type ConfirmationData,
  type ConfirmationJobType,
  type ConfirmationJobResult,
} from '../ChatWidgets'

export const AGENT_LABELS: Record<string, string> = {
  Aanya: 'Aanya · Orchestrator',
  productions_agent: 'Aanya · Productions Specialist',
  director: 'Aanya · Productions Specialist',
  reframe_agent: 'Aanya · Orientations Specialist',
  key_moments_agent: 'Aanya · Key Moments Specialist',
  thumbnails_agent: 'Aanya · Thumbnails Specialist',
  promo_agent: 'Aanya · Promo Specialist',
  adapts_agent: 'Aanya · Social Adapts Specialist',
  dubbing_agent: 'Aanya · Dubbing Specialist',
  finops_agent: 'Aanya · FinOps & Pricing Specialist',
}

export const STARTER_PROMPTS = [
  'Create a 30s coffee commercial production',
  'Reframe a video to 9:16 vertical',
  'Dub a video into Spanish and Hindi',
  'Create a 60s promo cutdown',
  'Compare costs of my recent productions',
]

export function formatChatMarkdown(content: string): string {
  if (!content) return ''
  return content
    .split('\n')
    .map((line) => {
      if (line.trimStart().startsWith('|')) {
        return line
          .replace(/<br\s*\/?>\s*[•*-]?\s*/gi, '; ')
          .replace(/\|\s*•\s*/g, '| ')
      }
      return line.replace(/<br\s*\/?>/gi, '\n')
    })
    .join('\n')
}

export function formatLatency(ms?: number): string | null {
  if (ms === undefined || ms === null || ms <= 0) return null
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export const ChatMarkdownBody: React.FC<{ content: string }> = ({ content }) => (
  <div className="prose prose-sm prose-slate dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_p]:my-1.5 [&_ol]:my-1.5 [&_ul]:my-1.5 [&_li]:my-0.5 [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[11px] dark:[&_code]:bg-slate-700">
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
            <table className="m-0 w-full border-collapse text-xs">{children}</table>
          </div>
        ),
        thead: ({ children }) => (
          <thead className="bg-slate-50 dark:bg-slate-700/60">{children}</thead>
        ),
        th: ({ children }) => (
          <th className="border-b border-r last:border-r-0 border-slate-200 px-3 py-2 text-left font-semibold text-slate-700 dark:border-slate-700 dark:text-slate-200">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border-b border-r last:border-r-0 border-slate-100 px-3 py-2 align-top text-slate-700 dark:border-slate-700/70 dark:text-slate-300">
            {children}
          </td>
        ),
      }}
    >
      {formatChatMarkdown(content)}
    </Markdown>
  </div>
)

export const SharedLinkBanner: React.FC<{
  sharedUrl: string
  sharedCopied: boolean
  onCopy: () => void
  onDismiss: () => void
}> = ({ sharedUrl, sharedCopied, onCopy, onDismiss }) => (
  <div className="flex items-center justify-between gap-2 border-b border-emerald-200 bg-emerald-50/90 px-4 py-2 text-xs text-emerald-900 dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-200">
    <div className="flex items-center gap-2 min-w-0">
      <Share2 size={13} className="shrink-0 text-emerald-600 dark:text-emerald-400" />
      <span className="font-medium shrink-0">
        {sharedCopied ? 'Public link copied:' : 'Public share link:'}
      </span>
      <span className="truncate font-mono text-[11px] opacity-90">{sharedUrl}</span>
    </div>
    <div className="flex items-center gap-1.5 shrink-0">
      <Button type="button" variant="outline" size="xs" onClick={onCopy} className="h-6 px-2 text-[11px]">
        {sharedCopied ? <Check size={12} /> : <Copy size={12} />}
        <span>{sharedCopied ? 'Copied' : 'Copy'}</span>
      </Button>
      <Button
        variant="outline"
        size="xs"
        href={sharedUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="h-6 px-2 text-[11px]"
      >
        <ExternalLink size={12} />
        <span>Open</span>
      </Button>
      <Button type="button" variant="ghost" size="xs" onClick={onDismiss} className="h-6 px-1.5 text-[11px]">
        Dismiss
      </Button>
    </div>
  </div>
)

export const ChatEmptyState: React.FC<{ onSelectPrompt: (prompt: string) => void }> = ({
  onSelectPrompt,
}) => (
  <div className="flex h-full flex-col items-center justify-center text-center">
    <div className="mb-3 rounded-full bg-orange-100 p-4 text-orange-600 dark:bg-orange-900/30 dark:text-orange-400">
      <Sparkles size={32} />
    </div>
    <h4 className="mb-1 text-sm font-medium text-slate-900 dark:text-white">
      Hi, I&apos;m Aanya!
    </h4>
    <p className="px-6 text-xs text-slate-500 max-w-md mb-4">
      Your multi-agent co-pilot with 8 specialized feature agents across Productions,
      Orientations, Key Moments, Thumbnails, Promos, Adapts, Dubbing, and FinOps.
    </p>
    <div className="flex flex-wrap justify-center gap-1.5 max-w-lg px-4">
      {STARTER_PROMPTS.map((prompt) => (
        <Button
          key={prompt}
          variant="outline"
          size="xs"
          onClick={() => onSelectPrompt(prompt)}
          className="text-[11px]"
        >
          {prompt}
        </Button>
      ))}
    </div>
  </div>
)

const ChatMessageWidgets: React.FC<{
  data?: Record<string, unknown>
  sendMessage: (text: string) => void
  onConfirmed: (jobType: ConfirmationJobType, result: ConfirmationJobResult, title: string) => void
  onFailed: (error: string) => void
}> = ({ data, sendMessage, onConfirmed, onFailed }) => {
  if (!data) return null
  const a2ui = data.a2ui as { kind?: string } | undefined
  const confirmationPayload = (
    a2ui?.kind === 'job_proposal' ? data.a2ui : data.confirmation
  ) as ConfirmationData | undefined

  return (
    <>
      {typeof data.job_id === 'string' && (
        <VideoResultCard
          id={data.job_id}
          type={(data.job_type as ConfirmationJobType) || 'production'}
          status={String(data.status || 'pending')}
          title={String(data.title || '')}
        />
      )}
      {data.source_picker === 'image' ? (
        <ImageSourcePicker onSelect={(uri, name) => sendMessage(`Use image "${name}" (URI: ${uri})`)} />
      ) : data.source_picker ? (
        <VideoSourcePicker onSelect={(uri, name, type) => sendMessage(`Use ${type} "${name}" (URI: ${uri})`)} />
      ) : null}
      {typeof data.prompt_picker === 'string' && (
        <PromptPicker
          category={data.prompt_picker}
          onSelect={(id, name) => sendMessage(`Use prompt "${name}" (ID: ${id})`)}
        />
      )}
      {confirmationPayload && (
        <ConfirmationCard
          confirmation={confirmationPayload}
          onConfirmed={(jt, res) => onConfirmed(jt, res, confirmationPayload.title)}
          onFailed={onFailed}
        />
      )}
    </>
  )
}

const ChatModelFooter: React.FC<{
  msg: Message
  index: number
  isCopied: boolean
  sharingDisabled: boolean
  onFeedback: (index: number, fb: 'up' | 'down' | undefined) => void
  onCopy: () => void
  onShare: () => void
}> = ({ msg, index, isCopied, sharingDisabled, onFeedback, onCopy, onShare }) => {
  const latencyLabel = formatLatency(msg.latencyMs)
  return (
    <div className="mt-2 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-1.5 text-[10px] text-slate-500 dark:border-slate-700/80 dark:text-slate-400">
      <div className="flex flex-wrap items-center gap-2">
        {msg.agent && (
          <span className="font-semibold uppercase tracking-wider">
            {AGENT_LABELS[msg.agent] || `${msg.agent} Agent`}
          </span>
        )}
        {latencyLabel && (
          <span
            className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-700/70 dark:text-slate-300"
            title="Response time"
          >
            <Clock size={10} />
            {latencyLabel}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1">
        <Button
          type="button"
          variant="unstyled"
          onClick={() => onFeedback(index, msg.feedback === 'up' ? undefined : 'up')}
          title="Helpful response"
          className={clsx(
            'inline-flex items-center justify-center rounded p-1 transition-colors',
            msg.feedback === 'up'
              ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300'
              : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200',
          )}
        >
          <ThumbsUp size={12} />
        </Button>
        <Button
          type="button"
          variant="unstyled"
          onClick={() => onFeedback(index, msg.feedback === 'down' ? undefined : 'down')}
          title="Unhelpful response"
          className={clsx(
            'inline-flex items-center justify-center rounded p-1 transition-colors',
            msg.feedback === 'down'
              ? 'bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-300'
              : 'text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200',
          )}
        >
          <ThumbsDown size={12} />
        </Button>
        <Button
          type="button"
          variant="unstyled"
          onClick={onCopy}
          title="Copy response"
          className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200"
        >
          {isCopied ? (
            <>
              <Check size={12} className="text-emerald-600" />
              <span className="text-[10px] font-medium text-emerald-600">Copied</span>
            </>
          ) : (
            <Copy size={12} />
          )}
        </Button>
        <Button
          type="button"
          variant="unstyled"
          onClick={onShare}
          disabled={sharingDisabled}
          title="Share this interaction publicly"
          className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200"
        >
          <Share2 size={12} />
        </Button>
      </div>
    </div>
  )
}

export const ChatMessageRow: React.FC<{
  msg: Message
  index: number
  isCopied: boolean
  sharingDisabled: boolean
  sendMessage: (text: string) => void
  onCopy: (text: string, index: number) => void
  onShare: () => void
  onFeedback: (index: number, fb: 'up' | 'down' | undefined) => void
  onConfirmed: (jobType: ConfirmationJobType, result: ConfirmationJobResult, title: string) => void
  onFailed: (error: string) => void
}> = ({
  msg,
  index,
  isCopied,
  sharingDisabled,
  sendMessage,
  onCopy,
  onShare,
  onFeedback,
  onConfirmed,
  onFailed,
}) => (
  <div className={clsx('flex w-full flex-col', msg.role === 'user' ? 'items-end' : 'items-start')}>
    <div className="flex max-w-[95%] items-end gap-2 md:max-w-[85%]">
      {msg.role === 'model' && (
        <div className="mb-1 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-orange-600 text-white shadow-sm">
          <Bot size={14} />
        </div>
      )}
      <div
        className={clsx(
          'group min-w-0 overflow-hidden rounded-2xl px-4 py-2.5 text-sm shadow-sm',
          msg.role === 'user'
            ? 'bg-orange-600 text-white rounded-br-none'
            : 'bg-white text-slate-900 border border-slate-200 rounded-bl-none dark:bg-slate-800 dark:text-white dark:border-slate-700',
        )}
      >
        {msg.role === 'user' ? (
          <div className="flex items-start justify-between gap-2">
            <div className="whitespace-pre-wrap">{msg.content}</div>
            <Button
              type="button"
              variant="unstyled"
              onClick={() => onCopy(msg.content, index)}
              title="Copy prompt"
              className="mt-0.5 shrink-0 rounded p-1 text-white/70 opacity-70 transition-opacity hover:bg-white/15 hover:text-white group-hover:opacity-100"
            >
              {isCopied ? <Check size={12} /> : <Copy size={12} />}
            </Button>
          </div>
        ) : (
          <ChatMarkdownBody content={msg.content} />
        )}
        <ChatMessageWidgets
          data={msg.data as Record<string, unknown> | undefined}
          sendMessage={sendMessage}
          onConfirmed={onConfirmed}
          onFailed={onFailed}
        />
        {msg.role === 'model' && (
          <ChatModelFooter
            msg={msg}
            index={index}
            isCopied={isCopied}
            sharingDisabled={sharingDisabled}
            onFeedback={onFeedback}
            onCopy={() => onCopy(msg.content, index)}
            onShare={onShare}
          />
        )}
      </div>
      {msg.role === 'user' && (
        <div className="mb-1 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
          <User size={14} />
        </div>
      )}
    </div>
  </div>
)
