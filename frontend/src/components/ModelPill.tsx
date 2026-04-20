import { Cpu } from 'lucide-react'

interface ModelPillProps {
  modelName: string | undefined
}

function formatModelName(code: string): string {
  return code
    .replace(/-preview$/, '')
    .replace(/-generate-\d+$/, '')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
    .replace(/\d+\.\d+/, v => v) // keep version numbers as-is
}

export const ModelPill = ({ modelName }: ModelPillProps) => {
  if (!modelName) return null
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-cyan-500/10 text-cyan-600 dark:text-cyan-400 border border-cyan-500/20">
      <Cpu size={9} />
      {formatModelName(modelName)}
    </span>
  )
}
