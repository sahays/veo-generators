import type { ReactNode } from 'react'
import { type LucideIcon, ArrowLeft, Loader2, MoreHorizontal, Play, RefreshCw, Scissors, Sparkles, Eye, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { NextAction, NextActionKind, StatusChip } from './studioStatus'

export interface StudioMenuItem {
  id: string
  label: string
  icon?: LucideIcon
  onSelect: () => void
  disabled?: boolean
  separatorBefore?: boolean
}

export interface StudioHeaderProps {
  title: string
  subtitle?: string
  meta: string[]
  status: StatusChip
  progress: { done: number; total: number }
  canWrite: boolean
  nextAction: NextAction
  onNextAction: () => void
  menuItems: StudioMenuItem[]
  onBack?: () => void
}

const ACTION_ICONS: Record<NextActionKind, LucideIcon> = {
  busy: Loader2, retry: RefreshCw, continue: Sparkles, review: Eye, stitch: Scissors, upgrade: Sparkles, view: Play,
}

const ProgressBar = ({ done, total }: { done: number; total: number }) => {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className="flex items-center gap-3" aria-label={`${done} of ${total} agents complete`}>
      <div className="h-1.5 w-full max-w-[220px] overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[11px] tabular-nums text-muted-foreground">{done}/{total} agents</span>
    </div>
  )
}

const OverflowMenu = ({ items }: { items: StudioMenuItem[] }) => (
  <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button variant="outline" size="icon" aria-label="More actions" icon={MoreHorizontal} />
    </DropdownMenuTrigger>
    <DropdownMenuContent>
      <DropdownMenuLabel>Production</DropdownMenuLabel>
      {items.map((item) => <MenuEntry key={item.id} item={item} />)}
    </DropdownMenuContent>
  </DropdownMenu>
)

const MenuEntry = ({ item }: { item: StudioMenuItem }): ReactNode => (
  <>
    {item.separatorBefore && <DropdownMenuSeparator />}
    <DropdownMenuItem icon={item.icon} disabled={item.disabled} onSelect={item.onSelect}>{item.label}</DropdownMenuItem>
  </>
)

/** One clear header: title + status, a single primary next action, and an overflow menu. */
export const StudioHeader = (p: StudioHeaderProps) => (
  <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
    <div className="flex min-w-0 items-start gap-3">
      {p.onBack && <Button variant="ghost" size="icon" icon={ArrowLeft} aria-label="Back to productions" onClick={p.onBack} />}
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="truncate text-xl font-heading font-semibold tracking-tight text-foreground">{p.title}</h1>
          <Badge variant={p.status.tone}>{p.status.label}</Badge>
          {!p.canWrite && <Badge variant="outline"><Lock size={10} /> Read only</Badge>}
        </div>
        <p className="line-clamp-1 max-w-3xl text-xs text-muted-foreground">
          {[...p.meta, p.subtitle].filter(Boolean).join(' · ')}
        </p>
        <ProgressBar done={p.progress.done} total={p.progress.total} />
      </div>
    </div>
    <div className="flex shrink-0 items-center gap-2">
      {p.canWrite && (
        <Button
          variant="primary"
          size="sm"
          icon={ACTION_ICONS[p.nextAction.kind]}
          className={p.nextAction.kind === 'busy' ? '[&_svg]:animate-spin' : undefined}
          disabled={p.nextAction.kind === 'busy'}
          onClick={p.onNextAction}
        >
          {p.nextAction.label}
        </Button>
      )}
      <OverflowMenu items={p.menuItems} />
    </div>
  </header>
)
