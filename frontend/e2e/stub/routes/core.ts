/**
 * Routes the app shell and shared widgets need on every page: auth, models,
 * pricing, uploads, media, plus the stub's own control routes (`/__stub/*`).
 */
import type { InsightUsage } from '../../../src/types/insights.ts'
import type { FeaturePricing, ServiceLineItem } from '../../../src/types/project.ts'
import { MODELS, MODEL_REGIONS, UPLOADS, modelDefaults, pricingFeatures } from '../data/catalog.ts'
import type { StubFeature } from '../lib/feature.ts'
import { HttpError } from '../lib/http.ts'
import { ok, route, type Route, type RouteContext } from '../lib/router.ts'
import { isValidId } from '../lib/validate.ts'
import { VIDEO_FILE, missingMedia, serveMedia } from '../media.ts'
import { completedUploads, lookupUpload } from './uploads.ts'

const API = '/api/v1'
const MODEL_NAMES: ReadonlyMap<string, string> = new Map(MODELS.map((m) => [m.code, m.name]))

/** One Gemini token line item, priced so that it adds up to the recorded cost. */
function usageLineItems(usage: InsightUsage): ServiceLineItem[] {
  const tokens = usage.input_tokens + usage.output_tokens
  if (tokens === 0) return []
  return [
    {
      id: 'gemini_text',
      label: `${MODEL_NAMES.get(usage.model_name) ?? usage.model_name} (text)`,
      unit: 'token',
      units: tokens,
      unit_cost_usd: usage.cost_usd / tokens,
      subtotal_usd: usage.cost_usd,
    },
  ]
}

/** `GET /pricing/usage/{feature}/{id}` → `FeaturePricing`, answered by the feature that owns the record. */
function usageHandler(features: readonly StubFeature[]) {
  const byName = new Map(features.map((feature) => [feature.name, feature]))
  return (ctx: RouteContext) => {
    const { feature, id } = ctx.params
    const lookup = byName.get(feature)?.usage
    if (!lookup) throw new HttpError(400, `Unknown feature: ${feature}`)
    const usage = isValidId(id) ? lookup(id) : undefined
    if (!usage) throw new HttpError(404, `${feature} ${id} not found`)
    const services = usageLineItems(usage)
    const pricing: FeaturePricing = { feature, services, total_usd: usage.cost_usd, confidence: 'high' }
    return ok(pricing)
  }
}

function listUploads(ctx: RouteContext) {
  const fileType = ctx.query.get('file_type')
  const url = ctx.mediaUrl(VIDEO_FILE)
  // Files uploaded through the stub's upload flow are newer than every catalog fixture.
  return [...completedUploads(), ...UPLOADS].filter((u) => !fileType || u.file_type === fileType).map((u) =>
    u.file_type === 'video' ? { ...u, signed_url: url } : { ...u },
  )
}

function getUpload(ctx: RouteContext) {
  const found = isValidId(ctx.params.id) ? lookupUpload(ctx.params.id) : undefined
  if (!found) throw new HttpError(404, 'Upload not found')
  return found.file_type === 'video' ? { ...found, signed_url: ctx.mediaUrl(VIDEO_FILE) } : { ...found }
}

/** Core routes; `features` supplies the per-feature usage lookups and reset hooks. */
export function coreRoutes(features: readonly StubFeature[]): Route[] {
  const resetAll = (): void => features.forEach((feature) => feature.reset())
  return [
    route('POST', `${API}/auth/validate`, () => ok({ valid: true, is_master: true, is_power: true })),
    route('GET', `${API}/models`, () => ok(MODELS)),
    route('GET', `${API}/models/defaults`, () => ok(modelDefaults())),
    route('GET', `${API}/models/regions`, () => ok(MODEL_REGIONS)),
    route('GET', `${API}/pricing/features`, () => ok(pricingFeatures())),
    route('GET', `${API}/pricing/usage/{feature}/{id}`, usageHandler(features)),
    route('GET', `${API}/uploads`, (ctx) => ok(listUploads(ctx))),
    route('GET', `${API}/uploads/{id}`, (ctx) => ok(getUpload(ctx))),
    route('GET', '/media/{file}', serveMedia),
    route('GET', '/__stub/health', async () => ok({ status: 'ok', missing_media: await missingMedia() })),
    route('POST', '/__stub/reset', () => {
      resetAll()
      return ok({ status: 'reset' })
    }),
  ]
}
