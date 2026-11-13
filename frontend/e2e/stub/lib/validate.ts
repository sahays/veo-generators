/**
 * Request validation shared by the feature route modules. `BodyFields` mirrors
 * a strict pydantic model: unknown keys, wrong types and out-of-range strings
 * are collected and reported together as one FastAPI-shaped 422.
 */
import { validationError, type JsonObject } from './http.ts'

/** Record and source ids (same pattern as the real API). */
export const ID_PATTERN = /^[A-Za-z0-9_\-]{1,128}$/
/** Model ids and regions. */
export const MODEL_PATTERN = /^[A-Za-z0-9._\-]+$/

export const isValidId = (value: string): boolean => ID_PATTERN.test(value)

interface StringRule {
  max: number
  required?: boolean
  pattern?: RegExp
}

export class BodyFields {
  private readonly body: JsonObject
  private readonly issues: Record<string, string> = {}

  constructor(body: JsonObject, allowedKeys: readonly string[]) {
    this.body = body
    const allowed = new Set(allowedKeys)
    for (const key of Object.keys(body)) {
      if (!allowed.has(key)) this.issues[key] = 'Extra inputs are not permitted'
    }
  }

  /** A string field; `null` and absent both read as undefined unless the field is required. */
  text(key: string, rule: StringRule): string | undefined {
    const value = this.body[key]
    if (value === undefined || value === null) {
      if (rule.required) this.issues[key] = 'Field required'
      return undefined
    }
    if (typeof value !== 'string') {
      this.issues[key] = 'Input should be a valid string'
      return undefined
    }
    if (rule.required && value.length === 0) this.issues[key] = 'String should have at least 1 character'
    else if (value.length > rule.max) this.issues[key] = `String should have at most ${rule.max} characters`
    else if (rule.pattern && !rule.pattern.test(value)) this.issues[key] = 'String does not match the expected pattern'
    return value
  }

  /** A required field that must be one of `options`. */
  choice<T extends string>(key: string, options: readonly T[]): T | undefined {
    const value = this.body[key]
    const found = options.find((option) => option === value)
    if (found === undefined) {
      this.issues[key] = `Input should be ${options.map((o) => `'${o}'`).join(' or ')}`
    }
    return found
  }

  /** Throws a 422 listing every problem found so far. */
  assertValid(): void {
    if (Object.keys(this.issues).length > 0) throw validationError(this.issues)
  }
}
