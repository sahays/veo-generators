import { useId } from 'react'

export interface FormStepProps {
  number: number
  title: string
  children: React.ReactNode
}

/** One numbered step of the create form. */
export function FormStep({ number, title, children }: FormStepProps): JSX.Element {
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="space-y-3 rounded-xl border border-border bg-card p-4">
      <h3 id={headingId} className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <span aria-hidden className="flex h-5 w-5 items-center justify-center rounded-full bg-accent/15 text-[11px] font-bold text-accent-dark">{number}</span>
        <span className="sr-only">Step {number}: </span>
        {title}
      </h3>
      {children}
    </section>
  )
}

const SPARK_WIDTH = 132
const SPARK_HEIGHT = 34
const SPARK_PAD = 2

/** Points of a 0..100 series as an SVG polyline inside the sparkline box. */
function sparkPoints(values: readonly number[]): string {
  const step = values.length > 1 ? (SPARK_WIDTH - 2 * SPARK_PAD) / (values.length - 1) : 0
  return values
    .map((value, i) => {
      const y = SPARK_HEIGHT - SPARK_PAD - (Math.min(Math.max(value, 0), 100) / 100) * (SPARK_HEIGHT - 2 * SPARK_PAD)
      return `${(SPARK_PAD + i * step).toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

/** Small preview of a template's curve (values 0..100, evenly spaced over the video). Decorative: the description says the same. */
export function Sparkline({ values }: { values: readonly number[] }): JSX.Element | null {
  if (values.length < 2) return null
  const line = sparkPoints(values)
  const area = `${SPARK_PAD},${SPARK_HEIGHT} ${line} ${SPARK_WIDTH - SPARK_PAD},${SPARK_HEIGHT}`
  return (
    <svg aria-hidden data-testid="template-sparkline" width={SPARK_WIDTH} height={SPARK_HEIGHT} viewBox={`0 0 ${SPARK_WIDTH} ${SPARK_HEIGHT}`} className="block">
      <polygon points={area} fill="var(--chart-1)" fillOpacity={0.16} />
      <polyline points={line} fill="none" stroke="var(--chart-1)" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
