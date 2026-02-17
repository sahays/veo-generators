import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, Plus, Check, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SelectCategory } from '@/types/project'
import { useProjectStore } from '@/store/useProjectStore'

interface CreatableSelectProps {
  category: SelectCategory
  label: string
  value?: string
  onChange: (value: string) => void
  placeholder?: string
}

export const CreatableSelect = ({
  category,
  label,
  value,
  onChange,
  placeholder = 'Select...',
}: CreatableSelectProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const { getOptions, addCustomOption } = useProjectStore()

  const options = getOptions(category)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node) &&
        !isModalOpen
      ) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isModalOpen])

  const handleCreateConfirm = (name: string, prompt: string) => {
    if (name.trim() && !options.includes(name.trim())) {
      addCustomOption(category, name.trim(), prompt.trim())
      onChange(name.trim())
    }
    setIsModalOpen(false)
    setIsOpen(false)
  }

  return (
    <>
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-muted-foreground">{label}</label>
        <div ref={containerRef} className="relative">
          <button
            type="button"
            onClick={() => setIsOpen(!isOpen)}
            className={cn(
              "flex items-center justify-between w-full px-3 py-2 rounded-lg text-sm transition-all duration-200",
              "glass bg-card border border-border hover:border-accent/50 focus:outline-none focus:ring-2 focus:ring-accent/30",
              isOpen && "ring-2 ring-accent/30 border-accent/50"
            )}
          >
            <span className={cn(value ? "text-foreground" : "text-muted-foreground")}>
              {value || placeholder}
            </span>
            <ChevronDown
              size={14}
              className={cn(
                "text-muted-foreground transition-transform duration-200",
                isOpen && "rotate-180"
              )}
            />
          </button>

          <AnimatePresence>
            {isOpen && (
              <motion.div
                initial={{ opacity: 0, y: -4, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -4, scale: 0.98 }}
                transition={{ duration: 0.15 }}
                className="absolute z-50 mt-1 w-full rounded-lg bg-background border border-border shadow-xl overflow-hidden"
              >
                <div className="max-h-52 overflow-y-auto py-1">
                  {options.map((option: string) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => {
                        onChange(option)
                        setIsOpen(false)
                      }}
                      className={cn(
                        "flex items-center justify-between w-full px-3 py-2 text-sm transition-colors",
                        "hover:bg-accent/20 hover:text-foreground",
                        value === option
                          ? "text-accent-dark font-medium bg-accent/10"
                          : "text-foreground"
                      )}
                    >
                      <span>{option}</span>
                      {value === option && <Check size={14} className="text-accent-dark" />}
                    </button>
                  ))}
                </div>

                <div className="border-t border-border">
                  <button
                    type="button"
                    onClick={() => {
                      setIsModalOpen(true)
                      setIsOpen(false)
                    }}
                    className="flex items-center gap-2 w-full px-3 py-2.5 text-sm text-accent-dark hover:bg-accent/10 transition-colors font-medium"
                  >
                    <Plus size={14} />
                    <span>Create New</span>
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      <AnimatePresence>
        {isModalOpen && (
          <CreateOptionModal
            label={label}
            onConfirm={handleCreateConfirm}
            onClose={() => setIsModalOpen(false)}
          />
        )}
      </AnimatePresence>
    </>
  )
}

// ─── Modal ───────────────────────────────────────────────────────────────────

interface CreateOptionModalProps {
  label: string
  onConfirm: (name: string, prompt: string) => void
  onClose: () => void
}

const CreateOptionModal = ({ label, onConfirm, onClose }: CreateOptionModalProps) => {
  const [name, setName] = useState('')
  const [prompt, setPrompt] = useState('')
  const nameRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    nameRef.current?.focus()
  }, [])

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [onClose])

  const handleSubmit = () => {
    if (name.trim()) {
      onConfirm(name, prompt)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
    >
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
      />

      {/* Dialog */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 10 }}
        transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        className="relative w-full max-w-md glass bg-card rounded-xl shadow-2xl border border-border overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <div>
            <h3 className="text-base font-heading font-bold text-foreground">
              New {label}
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              This will be saved and available in future projects.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 pb-2 space-y-4">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <input
              ref={nameRef}
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && name.trim()) {
                  e.preventDefault()
                  handleSubmit()
                }
              }}
              placeholder={`e.g. My custom ${label.toLowerCase()}`}
              className={cn(
                "w-full px-3 py-2 rounded-lg text-sm transition-all duration-200 text-foreground",
                "bg-muted border border-border placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/50"
              )}
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Prompt / Description
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              placeholder="Describe the style, behavior, or details for this option..."
              className={cn(
                "w-full px-3 py-2 rounded-lg text-sm transition-all duration-200 resize-none text-foreground",
                "bg-muted border border-border placeholder:text-muted-foreground",
                "focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent/50"
              )}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-border mt-2">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 rounded-lg text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!name.trim()}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200",
              "bg-accent text-slate-900 hover:bg-accent-dark shadow-sm",
              "disabled:opacity-40 disabled:cursor-not-allowed"
            )}
          >
            Create
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}
