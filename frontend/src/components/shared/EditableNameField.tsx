import { useState } from 'react'
import { Pencil, Check } from 'lucide-react'

interface EditableNameFieldProps {
  value: string
  onSave: (newName: string) => Promise<void>
  defaultText?: string
}

export const EditableNameField = ({ value, onSave, defaultText = 'Untitled' }: EditableNameFieldProps) => {
  const [isEditing, setIsEditing] = useState(false)
  const [editName, setEditName] = useState('')

  const displayValue = value || defaultText

  if (isEditing) {
    return (
      <form className="flex items-center gap-2" onSubmit={async (e) => {
        e.preventDefault()
        await onSave(editName)
        setIsEditing(false)
      }}>
        <input
          autoFocus
          value={editName}
          onChange={(e) => setEditName(e.target.value)}
          className="text-lg font-heading font-bold text-foreground bg-muted px-2 py-0.5 rounded border border-border focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <button type="submit" className="text-accent hover:text-accent-dark">
          <Check size={16} />
        </button>
      </form>
    )
  }

  return (
    <button
      className="flex items-center gap-2 text-lg font-heading font-bold text-foreground hover:text-accent-dark transition-colors"
      onClick={() => { setEditName(displayValue); setIsEditing(true) }}
    >
      {displayValue}
      <Pencil size={12} className="text-muted-foreground" />
    </button>
  )
}
