/**
 * Route table → segment trie.
 *
 * A route is `{method, path, handler}` where `path` may contain `{name}`
 * parameters, e.g. `/api/v1/scene-analysis/{id}/timeline`. Lookup walks the
 * trie one path segment at a time (O(depth), independent of how many routes
 * are registered) and always prefers a literal segment over a parameter, so
 * `/sources/uploads` wins over `/{id}` regardless of registration order.
 */
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { JsonObject } from './http.ts'

export type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'

export interface RouteContext {
  /** Decoded `{name}` path parameters. */
  params: Readonly<Record<string, string>>
  query: URLSearchParams
  /** Parses the JSON body (object or empty). Throws `HttpError(400)` on malformed input. */
  body: () => Promise<JsonObject>
  /** Absolute URL of a file served by this stub's `/media/{file}` route. */
  mediaUrl: (file: string) => string
  req: IncomingMessage
  res: ServerResponse
}

export interface Reply {
  status: number
  body: unknown
}

/** Returned by a handler that has already written the response itself (e.g. a file stream). */
export const STREAMED: unique symbol = Symbol('streamed')

export type HandlerResult = Reply | typeof STREAMED
export type Handler = (ctx: RouteContext) => HandlerResult | Promise<HandlerResult>

export interface Route {
  method: Method
  path: string
  handler: Handler
}

export type Match =
  | { kind: 'found'; handler: Handler; params: Record<string, string> }
  | { kind: 'method_not_allowed'; allow: Method[] }
  | { kind: 'not_found' }

interface Endpoint {
  handler: Handler
  paramNames: string[]
}

interface TrieNode {
  literals: Map<string, TrieNode>
  param: TrieNode | null
  endpoints: Map<Method, Endpoint>
}

const PARAM_SEGMENT = /^\{([A-Za-z_][A-Za-z0-9_]*)\}$/

export const ok = (body: unknown): Reply => ({ status: 200, body })

export const route = (method: Method, path: string, handler: Handler): Route => ({
  method,
  path,
  handler,
})

function newNode(): TrieNode {
  return { literals: new Map(), param: null, endpoints: new Map() }
}

function splitPath(path: string): string[] {
  return path.split('/').filter((segment) => segment.length > 0)
}

export class Router {
  private readonly root: TrieNode = newNode()

  constructor(routes: readonly Route[]) {
    for (const entry of routes) this.add(entry)
  }

  private add(entry: Route): void {
    let node = this.root
    const paramNames: string[] = []
    for (const segment of splitPath(entry.path)) {
      const param = PARAM_SEGMENT.exec(segment)
      if (param) paramNames.push(param[1])
      node = param ? (node.param ??= newNode()) : childOf(node, segment)
    }
    if (node.endpoints.has(entry.method)) {
      throw new Error(`Duplicate stub route: ${entry.method} ${entry.path}`)
    }
    node.endpoints.set(entry.method, { handler: entry.handler, paramNames })
  }

  /** `segments` must already be URI-decoded. */
  match(method: string, segments: readonly string[]): Match {
    const values: string[] = []
    const node = walk(this.root, segments, 0, values)
    if (!node) return { kind: 'not_found' }
    const endpoint = node.endpoints.get(method as Method)
    if (!endpoint) return { kind: 'method_not_allowed', allow: [...node.endpoints.keys()] }
    const params: Record<string, string> = {}
    endpoint.paramNames.forEach((name, i) => {
      params[name] = values[i]
    })
    return { kind: 'found', handler: endpoint.handler, params }
  }
}

function childOf(node: TrieNode, segment: string): TrieNode {
  let child = node.literals.get(segment)
  if (!child) {
    child = newNode()
    node.literals.set(segment, child)
  }
  return child
}

/** Depth-first: literal child first, then the parameter child; `values` collects parameter segments. */
function walk(
  node: TrieNode,
  segments: readonly string[],
  index: number,
  values: string[],
): TrieNode | null {
  if (index === segments.length) return node.endpoints.size > 0 ? node : null
  const segment = segments[index]
  const literal = node.literals.get(segment)
  const viaLiteral = literal ? walk(literal, segments, index + 1, values) : null
  if (viaLiteral) return viaLiteral
  if (!node.param) return null
  values.push(segment)
  const viaParam = walk(node.param, segments, index + 1, values)
  if (!viaParam) values.pop()
  return viaParam
}
