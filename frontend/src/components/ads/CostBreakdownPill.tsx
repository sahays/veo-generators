import { useState, useRef, useEffect } from 'react'
import { Cpu } from 'lucide-react'
import { cn } from '@/lib/utils'

const GEMINI_INPUT_RATE = 0.000002
const GEMINI_OUTPUT_RATE = 0.000012

interface CostBreakdownPillProps {
  inputTokens: number
  outputTokens: number
  totalCost: number
  className?: string
}

export const CostBreakdownPill = ({ inputTokens, outputTokens, totalCost, className }: CostBreakdownPillProps) => {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const geminiInputCost = inputTokens * GEMINI_INPUT_RATE
  const geminiOutputCost = outputTokens * GEMINI_OUTPUT_RATE
  const geminiTotal = geminiInputCost + geminiOutputCost
  const mediaCost = Math.max(0, totalCost - geminiTotal)

  const fmt = (n: number) => n >= 0.01 ? `$${n.toFixed(3)}` : `$${n.toFixed(4)}`

  return (
    <div ref={ref} className={cn("relative inline-flex", className)}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-accent/10 border border-accent/20 text-[9px] font-mono font-bold text-accent-dark hover:bg-accent/20 transition-colors"
      >
        <Cpu size={10} />
        <span>IN:{formatCount(inputTokens)}</span>
        <span className="text-muted-foreground">|</span>
        <span>OUT:{formatCount(outputTokens)}</span>
        <span className="text-muted-foreground">|</span>
        <span>{fmt(totalCost)}</span>
      </button>

      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute bottom-full left-0 mb-2 z-50 w-56 glass bg-card rounded-xl border border-border shadow-2xl p-3 space-y-2"
        >
          <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground">Cost Breakdown</p>
          <div className="space-y-1.5 text-xs font-mono">
            <Row label="Input tokens" value={inputTokens.toLocaleString()} cost={fmt(geminiInputCost)} />
            <Row label="Output tokens" value={outputTokens.toLocaleString()} cost={fmt(geminiOutputCost)} />
            <div className="border-t border-border/50 pt-1.5">
              <Row label="Gemini subtotal" cost={fmt(geminiTotal)} bold />
            </div>
            {mediaCost > 0 && (
              <Row label="Media (Imagen/Veo)" cost={fmt(mediaCost)} />
            )}
            <div className="border-t border-border/50 pt-1.5">
              <Row label="Total" cost={fmt(totalCost)} bold />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const Row = ({ label, value, cost, bold }: { label: string; value?: string; cost: string; bold?: boolean }) => (
  <div className={cn("flex items-center justify-between gap-2", bold && "font-bold")}>
    <span className="text-muted-foreground">{label}</span>
    <span className="flex items-center gap-2">
      {value && <span className="text-foreground/60">{value}</span>}
      <span className="text-accent-dark">{cost}</span>
    </span>
  </div>
)

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}
