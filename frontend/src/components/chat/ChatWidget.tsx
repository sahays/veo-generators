import React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { MessageCircle, X, Bot } from 'lucide-react'
import { useChatStore } from '@/store/useChatStore'
import { ChatWindow } from './ChatWindow'
import { clsx } from 'clsx'

export const ChatWidget: React.FC = () => {
  const { isOpen, setIsOpen } = useChatStore()

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end">
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.95 }}
            className="mb-4 flex h-[600px] w-[400px] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-900"
          >
            {/* Header */}
            <div className="flex items-center justify-between bg-slate-900 px-4 py-3 text-white">
              <div className="flex items-center gap-2">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500">
                  <Bot size={20} />
                </div>
                <div>
                  <h3 className="text-sm font-semibold">Ask Aanya</h3>
                  <div className="flex items-center gap-1.5">
                    <div className="h-1.5 w-1.5 animate-pulse rounded-full bg-green-400" />
                    <span className="text-[10px] text-slate-400">Multi-Agent System Online</span>
                  </div>
                </div>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                className="rounded-lg p-1 transition-colors hover:bg-slate-800"
              >
                <X size={20} />
              </button>
            </div>

            {/* Chat Body */}
            <div className="flex-1 overflow-hidden">
               <ChatWindow showClearHistory={false} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <button
        onClick={() => setIsOpen(!isOpen)}
        className={clsx(
          "flex h-14 w-14 items-center justify-center rounded-full shadow-lg transition-all active:scale-90 hover:scale-105",
          isOpen ? "bg-slate-200 text-slate-900 dark:bg-slate-800 dark:text-white" : "bg-indigo-600 text-white"
        )}
      >
        {isOpen ? <X size={28} /> : <MessageCircle size={28} />}
      </button>
    </div>
  )
}
