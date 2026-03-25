interface ErrorDisplayProps {
  error: string | null
  size?: 'sm' | 'md'
}

export function ErrorDisplay({ error, size = 'sm' }: ErrorDisplayProps): JSX.Element | null {
  if (!error) return null

  const padding = size === 'sm' ? 'p-3' : 'p-4'
  const text = size === 'sm' ? 'text-xs' : 'text-sm'

  return (
    <div className={`${padding} rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 ${text}`}>
      {error}
    </div>
  )
}
