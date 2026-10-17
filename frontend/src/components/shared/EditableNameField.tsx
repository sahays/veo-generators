import { useState } from 'react'
import { Pencil, Check } from 'lucide-react'
import { useAuthStore } from '@/store/useAuthStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface EditableNameFieldProps {
  value: string
  onSave: (newName: string) => Promise<void>
  defaultText?: string
}

const EditableNameForm = ({
  editName,
  setEditName,
  onSubmit,
}: {
  editName: string
  setEditName: (val: string) => void
  onSubmit: () => Promise<void>
}) => (
  <form
    className="flex items-center gap-2"
    onSubmit={async (e) => {
      e.preventDefault()
      await onSubmit()
    }}
  >
    <Input
      autoFocus
      value={editName}
      onChange={(e) => setEditName(e.target.value)}
      className="text-lg font-heading font-bold bg-muted px-2.5 py-1 w-auto"
    />
    <Button type="submit" variant="ghost" size="icon" className="text-accent hover:text-accent-dark">
      <Check size={16} />
    </Button>
  </form>
)

export const EditableNameField = ({ value, onSave, defaultText = 'Untitled' }: EditableNameFieldProps) => {
  const canWrite = useAuthStore((s) => s.isMaster || s.isPower)
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const displayValue = value || defaultText

  if (!canWrite) return <h2 className="text-lg font-heading font-bold text-foreground">{displayValue}</h2>

  if (isEditing) {
    return (
      <EditableNameForm editName={editName} setEditName={setEditName} onSubmit={async () => { await onSave(editName); setIsEditing(false) }} />
    )
  }

  return (
    <Button variant="link" className="flex items-center gap-2 text-lg font-heading font-bold text-foreground hover:text-accent-dark" onClick={() => { setEditName(displayValue); setIsEditing(true) }}>
      {displayValue}
      <Pencil size={12} className="text-muted-foreground" />
    </Button>
  )
}
