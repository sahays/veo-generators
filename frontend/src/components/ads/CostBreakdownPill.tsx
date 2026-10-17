import { useState, useRef, useEffect } from 'react'
import { Cpu } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface CostBreakdownPillProps {
  totalCost: number
  subtotals?: { label: string; cost: number; detail?: string }[]
  inputTokens?: number
  outputTokens?: number
  imageGenerations?: number
  imageCost?: number
  veoVideos?: number
  veoSeconds?: number
  veoUnitCost?: number
  veoCost?: number
  className?: string
}

const fmtCost = (n: number) => (n >= 0.01 ? `$${n.toFixed(3)}` : `$${n.toFixed(4)}`)

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

const Row = ({ label, value, cost, bold }: { label: string; value?: string; cost?: string; bold?: boolean }) => (
  <div className={cn('flex items-center justify-between gap-2', bold && 'font-bold')}>
    <span className="text-muted-foreground">{label}</span>
    <span className="flex items-center gap-2">
      {value && <span className="text-foreground/60">{value}</span>}
      {cost && <span className="text-accent-dark">{cost}</span>}
    </span>
  </div>
)

const CostPopover = ({
  totalCost,
  subtotals,
  hasLegacyTokens,
  inputTokens,
  outputTokens,
  imageGenerations,
  imageCost,
  veoVideos,
  veoSeconds,
  veoUnitCost,
  veoCost,
}: CostBreakdownPillProps & { hasLegacyTokens: boolean }) => (
  <div
    onClick={(e) => e.stopPropagation()}
    className="absolute bottom-full left-0 mb-2 z-50 w-60 glass bg-card rounded-xl border border-border shadow-2xl p-3 space-y-2"
  >
    <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground">Cost Breakdown</p>
    <div className="space-y-1.5 text-xs font-mono">
      {subtotals && subtotals.length > 0 ? (
        subtotals.map((s, i) => <Row key={i} label={s.label} value={s.detail} cost={fmtCost(s.cost)} />)
      ) : (
        <>
          {hasLegacyTokens && (
            <>
              <Row label="Input tokens" value={(inputTokens || 0).toLocaleString()} />
              <Row label="Output tokens" value={(outputTokens || 0).toLocaleString()} />
            </>
          )}
          {(imageGenerations ?? 0) > 0 && (
            <div className="border-t border-border/50 pt-1.5">
              <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Images</p>
              <Row label="Frames generated" value={String(imageGenerations)} />
              <Row label="Images subtotal" cost={fmtCost(imageCost || 0)} bold />
            </div>
          )}
          {(veoVideos ?? 0) > 0 && (
            <div className="border-t border-border/50 pt-1.5">
              <p className="text-[9px] font-bold uppercase tracking-widest text-muted-foreground mb-1">Videos</p>
              <Row label="Videos generated" value={String(veoVideos)} />
              <Row label="Total seconds" value={String(veoSeconds)} />
              <Row label="Unit cost" value={`${fmtCost(veoUnitCost || 0)}/s`} />
              <Row label="Videos subtotal" cost={fmtCost(veoCost || 0)} bold />
            </div>
          )}
        </>
      )}
      <div className="border-t border-border/50 pt-1.5">
        <Row label="Total" cost={fmtCost(totalCost)} bold />
      </div>
    </div>
  </div>
)

const PillTriggerButton = ({
  hasLegacyTokens,
  inputTokens,
  outputTokens,
  totalCost,
  onToggle,
}: {
  hasLegacyTokens: boolean
  inputTokens?: number
  outputTokens?: number
  totalCost: number
  onToggle: () => void
}) => (
  <Button
    variant="unstyled"
    onClick={(e) => {
      e.stopPropagation()
      onToggle()
    }}
    className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-accent/10 border border-accent/20 text-[9px] font-mono font-bold text-accent-dark hover:bg-accent/20 transition-colors"
  >
    <Cpu size={10} />
    {hasLegacyTokens && (
      <>
        <span>IN:{formatCount(inputTokens || 0)}</span>
        <span className="text-muted-foreground">|</span>
        <span>OUT:{formatCount(outputTokens || 0)}</span>
        <span className="text-muted-foreground">|</span>
      </>
    )}
    <span>{fmtCost(totalCost)}</span>
  </Button>
)

export const CostBreakdownPill = (props: CostBreakdownPillProps) => {
  const { totalCost, inputTokens, outputTokens, className } = props
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

  const hasLegacyTokens = inputTokens !== undefined || outputTokens !== undefined
  return (
    <div ref={ref} className={cn('relative inline-flex', className)}>
      <PillTriggerButton
        hasLegacyTokens={hasLegacyTokens}
        inputTokens={inputTokens}
        outputTokens={outputTokens}
        totalCost={totalCost}
        onToggle={() => setOpen(!open)}
      />
      {open && <CostPopover {...props} hasLegacyTokens={hasLegacyTokens} />}
    </div>
  )
}
