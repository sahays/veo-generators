import React, { useState, useRef, useEffect } from 'react'
import { Send, Bot, User, Loader2, Sparkles, Trash2 } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChatStore } from '@/store/useChatStore'
import { VideoResultCard, VideoSourcePicker, PromptPicker, ConfirmationCard } from './ChatWidgets'
import { clsx } from 'clsx'

interface ChatWindowProps {
  showClearHistory?: boolean
}

export const ChatWindow: React.FC<ChatWindowProps> = ({ showClearHistory = true }) => {
  const { messages, sendMessage, isTyping, clearHistory, addSystemMessage } = useChatStore()
  const [inputValue, setInputValue] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isTyping])

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inputValue.trim() || isTyping) return

    const text = inputValue.trim()
    setInputValue('')
    await sendMessage(text)
  }

  return (
    <div className="flex flex-col h-full bg-white dark:bg-slate-900">
      {/* Messages Area */}
      <div 
        ref={scrollRef}
        className="flex-1 overflow-y-auto bg-slate-50 p-4 space-y-4 scrollbar-thin dark:bg-slate-950"
      >
        {messages.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <div className="mb-3 rounded-full bg-indigo-100 p-4 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400">
              <Sparkles size={32} />
            </div>
            <h4 className="mb-1 text-sm font-medium text-slate-900 dark:text-white">Hi, I'm Aanya!</h4>
            <p className="px-6 text-xs text-slate-500 max-w-sm">
              I'm your AI assistant for video production. How can I help you today?
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <div
            key={i}
            className={clsx(
              "flex w-full flex-col",
              msg.role === 'user' ? "items-end" : "items-start"
            )}
          >
            <div className="flex max-w-[90%] items-end gap-2 md:max-w-[80%]">
              {msg.role === 'model' && (
                <div className="mb-1 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-indigo-600 text-white shadow-sm">
                  <Bot size={14} />
                </div>
              )}
              <div
                className={clsx(
                  "rounded-2xl px-4 py-2 text-sm shadow-sm",
                  msg.role === 'user'
                    ? "bg-indigo-600 text-white rounded-br-none"
                    : "bg-white text-slate-900 border border-slate-200 rounded-bl-none dark:bg-slate-800 dark:text-white dark:border-slate-700"
                )}
              >
                {msg.role === 'user' ? (
                  <div className="whitespace-pre-wrap">{msg.content}</div>
                ) : (
                  <div className="prose prose-sm prose-slate dark:prose-invert max-w-none [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_p]:my-1 [&_ol]:my-1 [&_ul]:my-1 [&_li]:my-0.5 [&_code]:rounded [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[11px] dark:[&_code]:bg-slate-700 [&_table]:my-2 [&_table]:w-full [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1 dark:[&_th]:border-slate-700 dark:[&_th]:bg-slate-700/50 dark:[&_td]:border-slate-700">
                    <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
                  </div>
                )}
                
                {/* Rich Widgets */}
                {msg.data?.job_id && (
                  <VideoResultCard 
                    id={msg.data.job_id} 
                    type={msg.data.job_type} 
                    status={msg.data.status || 'pending'}
                    title={msg.data.title}
                  />
                )}

                {msg.data?.source_picker && (
                  <VideoSourcePicker 
                    onSelect={(uri, name, type) => {
                      setInputValue(`Use ${type} "${name}" (URI: ${uri})`)
                    }}
                  />
                )}

                {msg.data?.prompt_picker && (
                  <PromptPicker
                    category={msg.data.prompt_picker}
                    onSelect={(id, name) => {
                      setInputValue(`Use prompt "${name}" (ID: ${id})`)
                    }}
                  />
                )}

                {msg.data?.confirmation && (
                  <ConfirmationCard
                    confirmation={msg.data.confirmation}
                    onConfirmed={(jobType, result) => {
                      addSystemMessage('Job created successfully!', {
                        job_id: result.id,
                        job_type: jobType,
                        status: result.status || 'pending',
                        title: result.name || result.display_name || '',
                      })
                    }}
                    onFailed={(error) => addSystemMessage(`Failed to create job: ${error}`)}
                  />
                )}

                {msg.agent && (
                  <div className="mt-1 flex items-center gap-1 border-t border-slate-100 pt-1 text-[10px] text-slate-500 dark:border-slate-700">
                    <span className="font-semibold uppercase tracking-wider">{msg.agent} Agent</span>
                  </div>
                )}
              </div>
              {msg.role === 'user' && (
                <div className="mb-1 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                  <User size={14} />
                </div>
              )}
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="flex items-start gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-600 text-white">
              <Bot size={14} />
            </div>
            <div className="flex items-center gap-1 rounded-2xl bg-white px-4 py-3 border border-slate-200 shadow-sm dark:bg-slate-800 dark:border-slate-700">
              <Loader2 size={16} className="animate-spin text-indigo-500" />
              <span className="text-xs text-slate-500">Thinking...</span>
            </div>
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="border-t border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <form onSubmit={handleSend} className="max-w-4xl mx-auto flex gap-2">
          {showClearHistory && (
             <button
              type="button"
              onClick={clearHistory}
              title="Clear history"
              className="flex items-center justify-center p-2 rounded-xl border border-slate-200 text-slate-400 hover:text-red-500 hover:border-red-200 transition-colors dark:border-slate-700"
            >
              <Trash2 size={20} />
            </button>
          )}
          <div className="relative flex-1">
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="Ask a question or request a task..."
              className="w-full rounded-xl border border-slate-200 bg-slate-50 py-2.5 pl-4 pr-12 text-sm transition-all focus:border-indigo-500 focus:bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/20 dark:border-slate-700 dark:bg-slate-800 dark:text-white dark:focus:border-indigo-400 dark:focus:bg-slate-900"
            />
            <button
              type="submit"
              disabled={!inputValue.trim() || isTyping}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white transition-all hover:bg-indigo-500 disabled:bg-slate-300 disabled:text-slate-500 dark:disabled:bg-slate-700 dark:disabled:text-slate-500"
            >
              <Send size={16} />
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
