import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronDown, Check } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface SelectOption {
  value: string
  label: string
  description?: string
  className?: string
}

export interface SelectProps {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  label?: string
  error?: string
  className?: string
}

function useSelectDismiss(containerRef: React.RefObject<HTMLDivElement | null>, setIsOpen: (open: boolean) => void): void {
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEsc)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEsc)
    }
  }, [containerRef, setIsOpen])
}

const SelectOptionButton = ({
  opt,
  isSelected,
  onSelect,
}: {
  opt: SelectOption
  isSelected: boolean
  onSelect: () => void
}) => (
  <button
    type="button"
    onClick={onSelect}
    className={cn(
      'w-full flex items-center justify-between px-3 py-2 text-xs transition-all hover:bg-gradient-to-r hover:from-orange-500/15 hover:to-amber-500/10 hover:text-foreground group',
      isSelected ? 'bg-accent/12 text-accent-dark font-medium' : 'text-foreground',
      opt.className,
    )}
  >
    <div className="flex flex-col items-start text-left">
      <span>{opt.label}</span>
      {opt.description && (
        <span className="text-[10px] text-muted-foreground group-hover:text-foreground/75">{opt.description}</span>
      )}
    </div>
    {isSelected && <Check size={14} className="text-accent shrink-0 ml-2" />}
  </button>
)

const SelectDropdownMenu = ({
  isOpen,
  openUpwards,
  options,
  value,
  onSelect,
}: {
  isOpen: boolean
  openUpwards: boolean
  options: SelectOption[]
  value: string
  onSelect: (val: string) => void
}) => (
  <AnimatePresence>
    {isOpen && (
      <motion.div
        initial={{ opacity: 0, y: openUpwards ? 8 : -8, scale: 0.97 }}
        animate={{ opacity: 1, y: openUpwards ? -4 : 4, scale: 1 }}
        exit={{ opacity: 0, y: openUpwards ? 8 : -8, scale: 0.97 }}
        transition={{ type: 'spring', stiffness: 450, damping: 28 }}
        className={cn(
          'absolute z-[60] w-full bg-popover border border-border rounded-xl shadow-2xl overflow-hidden py-1',
          openUpwards ? 'bottom-full mb-1' : 'top-full mt-1',
        )}
      >
        <div className="max-h-60 overflow-y-auto no-scrollbar">
          {options.map((opt) => (
            <SelectOptionButton key={opt.value} opt={opt} isSelected={value === opt.value} onSelect={() => onSelect(opt.value)} />
          ))}
        </div>
      </motion.div>
    )}
  </AnimatePresence>
)

export const Select = ({ value, onChange, options, placeholder = 'Select option...', label, error, className }: SelectProps) => {
  const [isOpen, setIsOpen] = useState(false)
  const [openUpwards, setOpenUpwards] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const selectedOption = options.find((o) => o.value === value)
  useSelectDismiss(containerRef, setIsOpen)

  const handleToggle = () => {
    if (!isOpen && containerRef.current) setOpenUpwards(window.innerHeight - containerRef.current.getBoundingClientRect().bottom < 220)
    setIsOpen(!isOpen)
  }

  return (
    <div className={cn('space-y-1.5 w-full relative', className)} ref={containerRef}>
      {label && <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1">{label}</label>}
      <div className="relative">
        <button
          type="button"
          onClick={handleToggle}
          className={cn(
            'w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm transition-all duration-200 border text-left bg-card hover:bg-muted/80 hover:border-accent/40',
            isOpen ? 'border-accent ring-2 ring-accent/20 shadow-glow-sm' : 'border-border',
            error && 'border-red-500/50 ring-red-500/20',
          )}
        >
          <span className={cn('truncate', !selectedOption && 'text-muted-foreground')}>{selectedOption ? selectedOption.label : placeholder}</span>
          <ChevronDown size={16} className={cn('text-muted-foreground transition-transform duration-200 shrink-0 ml-2', isOpen && 'rotate-180 text-accent')} />
        </button>
        <SelectDropdownMenu isOpen={isOpen} openUpwards={openUpwards} options={options} value={value} onSelect={(val) => { onChange(val); setIsOpen(false) }} />
      </div>
      {error && <p className="text-[10px] text-red-500 ml-1">{error}</p>}
    </div>
  )
}

export interface NativeSelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
}

export const NativeSelect = ({
  className,
  label,
  error,
  children,
  ...props
}: NativeSelectProps) => {
  const selectEl = (
    <select
      className={cn(
        'px-3 py-2 rounded-[5px] bg-card border border-border text-sm text-foreground transition-all duration-200 focus:outline-none focus:border-accent focus:ring-2 focus:ring-accent/20 hover:border-accent/40 disabled:opacity-50',
        error && 'border-red-500/60 focus:border-red-500',
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )

  if (!label && !error) return selectEl

  return (
    <div className="space-y-1.5 w-full">
      {label && (
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground ml-1 block">
          {label}
        </label>
      )}
      {selectEl}
      {error && <p className="text-[10px] text-red-500 ml-1">{error}</p>}
    </div>
  )
}
