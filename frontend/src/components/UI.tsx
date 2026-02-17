import React, { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, Check, X } from 'lucide-react'
import { cn } from '@/lib/utils'

// ─── Modal ───────────────────────────────────────────────────────────────────

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  maxWidth?: string
}

export const Modal = ({ isOpen, onClose, title, children, maxWidth = 'max-w-2xl' }: ModalProps) => {
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) document.addEventListener('keydown', handleEsc)
    return () => document.removeEventListener('keydown', handleEsc)
  }, [isOpen, onClose])

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className={cn(
              "relative w-full bg-background rounded-2xl shadow-2xl border border-border flex flex-col overflow-hidden max-h-[90vh]",
              maxWidth
            )}
          >
            <div className="px-6 py-4 border-b border-border flex items-center justify-between">
              <h3 className="text-lg font-heading font-bold text-foreground">{title}</h3>
              <button
                onClick={onClose}
                className="p-1 rounded-lg hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
              >
                <X size={20} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              {children}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  )
}

// ─── Select ──────────────────────────────────────────────────────────────────

interface SelectOption {
  value: string
  label: string
  description?: string
  className?: string
}

interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  label?: string
  error?: string
  className?: string
}

export const Select = ({
  value,
  onChange,
  options,
  placeholder = 'Select option...',
  label,
  error,
  className
}: SelectProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const [openUpwards, setOpenUpwards] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  
  const selectedOption = options.find(o => o.value === value)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleToggle = () => {
    if (!isOpen && containerRef.current) {
      const rect = containerRef.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom
      // If less than 200px below, open upwards
      setOpenUpwards(spaceBelow < 200)
    }
    setIsOpen(!isOpen)
  }

  return (
    <div className={cn("space-y-1.5 w-full relative", className)} ref={containerRef}>
      {label && (
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">
          {label}
        </label>
      )}
      
      <div className="relative">
        <button
          type="button"
          onClick={handleToggle}
          className={cn(
            "w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-all duration-200 border text-left",
            "bg-card hover:bg-muted/80",
            isOpen ? "border-accent ring-2 ring-accent/20" : "border-border",
            error && "border-red-500/50 ring-red-500/20"
          )}
        >
          <span className={cn("truncate", !selectedOption && "text-muted-foreground")}>
            {selectedOption ? selectedOption.label : placeholder}
          </span>
          <ChevronDown 
            size={16} 
            className={cn("text-muted-foreground transition-transform duration-200", isOpen && "rotate-180")} 
          />
        </button>

        <AnimatePresence>
          {isOpen && (
            <motion.div
              initial={{ opacity: 0, y: openUpwards ? 10 : -10, scale: 0.98 }}
              animate={{ opacity: 1, y: openUpwards ? -4 : 4, scale: 1 }}
              exit={{ opacity: 0, y: openUpwards ? 10 : -10, scale: 0.98 }}
              className={cn(
                "absolute z-[60] w-full bg-background border border-border rounded-xl shadow-2xl overflow-hidden py-1",
                openUpwards ? "bottom-full mb-1" : "top-full mt-1"
              )}
            >
              <div className="max-h-60 overflow-y-auto no-scrollbar">
                {options.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => {
                      onChange(opt.value)
                      setIsOpen(false)
                    }}
                    className={cn(
                      "w-full flex items-center justify-between px-3 py-2 text-xs transition-colors hover:bg-accent hover:text-slate-900 group",
                      value === opt.value ? "bg-accent/10 text-accent-dark font-medium" : "text-foreground",
                      opt.className
                    )}
                  >
                    <div className="flex flex-col">
                      <span>{opt.label}</span>
                      {opt.description && (
                        <span className="text-[10px] text-muted-foreground group-hover:text-slate-900/70">
                          {opt.description}
                        </span>
                      )}
                    </div>
                    {value === opt.value && <Check size={14} className="text-accent-dark group-hover:text-slate-900" />}
                  </button>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      
      {error && <p className="text-[10px] text-red-500 ml-1">{error}</p>}
    </div>
  )
}
