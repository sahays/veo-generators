import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ZodType, ZodTypeDef } from 'zod'

export interface CreateRecordOptions<TPayload> {
  /** Zod schema of the create request. */
  schema: ZodType<TPayload, ZodTypeDef, unknown>
  /** Sends the validated request and resolves with the new record's id. */
  send: (payload: TPayload) => Promise<{ id: string }>
  /** The new record opens at `${detailPath}/${id}`. */
  detailPath: string
  /** Shown when validation fails without a message of its own. */
  invalidMessage: string
  /** Shown when the request fails without a message of its own. */
  failureMessage: string
}

export interface CreateRecord {
  submitting: boolean
  error: string | null
  submit: (payload: unknown) => Promise<void>
}

/**
 * Submit handler of a "new job" form: validate the payload with Zod, send it,
 * and open the created record (replacing the form in the history).
 */
export function useCreateRecord<TPayload>(options: CreateRecordOptions<TPayload>): CreateRecord {
  const navigate = useNavigate()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (payload: unknown): Promise<void> => {
    const parsed = options.schema.safeParse(payload)
    if (!parsed.success) {
      setError(parsed.error.issues[0]?.message || options.invalidMessage)
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      const created = await options.send(parsed.data)
      navigate(`${options.detailPath}/${created.id}`, { replace: true })
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : options.failureMessage)
    } finally {
      setSubmitting(false)
    }
  }

  return { submitting, error, submit }
}
