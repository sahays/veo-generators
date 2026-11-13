/**
 * One-line JSON logger for the stub server (stdout only).
 * Fields follow the repo's semantic logging: who / where / what / why / how.
 * Never pass request headers or bodies here: they can carry an invite code.
 */
export type LogLevel = 'info' | 'warn' | 'error'

export interface LogFields {
  who: string
  where: string
  what: string
  why?: string
  how?: string
  [extra: string]: string | number | boolean | null | undefined
}

export function log(level: LogLevel, fields: LogFields): void {
  const line = JSON.stringify({ when: new Date().toISOString(), level, ...fields })
  process.stdout.write(`${line}\n`)
}
