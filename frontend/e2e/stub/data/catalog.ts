/**
 * Static fixtures for the routes the app shell and shared widgets call:
 * models, pricing catalogue, uploads and completed productions.
 * Every `gs://` URI here is fake; nothing in the stub talks to Google Cloud.
 */
import type { FeatureId } from '../../../src/types/project.ts'
import type { UploadRecord } from '../../../src/types/records.ts'

export const TEXT_MODEL_CODE = 'gemini-3.8-flash'
export const TEXT_MODEL_NAME = 'Gemini 3.8 Flash'
export const DEFAULT_REGION = 'global'

export interface StubModel {
  id: string
  name: string
  code: string
  provider: string
  capability: 'text' | 'image' | 'video'
  regions: string[]
  is_default: boolean
  is_active: boolean
}

export interface StubProduction {
  id: string
  name: string
  orientation: string
  final_video_url: string
  createdAt: string
}

export interface CatalogService {
  id: string
  label: string
  unit: 'token' | 'image' | 'second' | 'minute'
  unit_cost_usd: number
  detail?: string
}

const model = (
  capability: StubModel['capability'],
  code: string,
  name: string,
): StubModel => ({
  id: `model-${code}`,
  name,
  code,
  provider: 'google',
  capability,
  regions: [DEFAULT_REGION, 'us-central1'],
  is_default: true,
  is_active: true,
})

export const MODELS: readonly StubModel[] = [
  model('text', TEXT_MODEL_CODE, TEXT_MODEL_NAME),
  model('image', 'gemini-nano-banana-2.1', 'Gemini Nano Banana 2.1'),
  model('video', 'gemini-omni-1.1-flash-preview', 'Gemini Omni 1.1 Flash'),
]

export const MODEL_REGIONS: readonly string[] = [DEFAULT_REGION, 'us-central1', 'asia-south1']

/** `GET /models/defaults`: capability → `{code, name, region}` (see `ModelRegionPicker`). */
export function modelDefaults(): Record<string, { code: string; name: string; region: string }> {
  return Object.fromEntries(
    MODELS.map((m) => [m.capability, { code: m.code, name: m.name, region: DEFAULT_REGION }]),
  )
}

const GEMINI_TEXT_SERVICE: CatalogService = {
  id: 'gemini_text',
  label: `${TEXT_MODEL_NAME} (text)`,
  unit: 'token',
  unit_cost_usd: 0.0000025,
  detail: 'input 0.30/1M, output 2.50/1M USD',
}

const FEATURE_IDS: readonly FeatureId[] = [
  'production',
  'adapts',
  'reframe',
  'promo',
  'key_moments',
  'thumbnails',
  'scene_analysis',
  'engagement',
]

/** `GET /pricing/features`: every feature bills the text model in this stub. */
export function pricingFeatures(): { features: Record<string, { services: CatalogService[] }> } {
  return {
    features: Object.fromEntries(
      FEATURE_IDS.map((feature) => [feature, { services: [GEMINI_TEXT_SERVICE] }]),
    ),
  }
}

const upload = (
  id: string,
  filename: string,
  displayName: string,
  sizeBytes: number,
  createdAt: string,
  kind: { mime_type: string; file_type: UploadRecord['file_type'] } = {
    mime_type: 'video/mp4',
    file_type: 'video',
  },
): UploadRecord => ({
  id,
  filename,
  display_name: displayName,
  ...kind,
  gcs_uri: `gs://fixture-bucket/uploads/${filename}`,
  file_size_bytes: sizeBytes,
  status: 'completed',
  compressed_variants: [],
  archived: false,
  createdAt,
})

/** Newest first. `upl-fixture-ad-spot` is the source of the completed fixture analysis. */
export const UPLOADS: readonly UploadRecord[] = [
  upload('upl-fixture-cricket', 'cricket-final-highlights-90s.mp4', 'Cricket final highlights (90s)', 48_211_004, '2026-11-13T04:10:00Z'),
  upload('upl-fixture-trailer', 'monsoon-drama-trailer.mp4', 'Monsoon drama trailer', 31_870_432, '2026-11-12T15:45:00Z'),
  upload('upl-fixture-ad-spot', 'kadak-chai-monsoon-45s.mp4', 'Kadak Chai — Monsoon (45s)', 12_402_688, '2026-11-12T09:20:00Z'),
  // The input of the Engagement BARC fixtures (`data/engagement/`); the name selects its signal preview.
  upload('upl-fixture-barc-csv', 'barc-kadak-chai-monsoon.csv', 'barc-kadak-chai-monsoon.csv', 5_983, '2026-11-11T11:00:00Z', {
    mime_type: 'text/csv',
    file_type: 'other',
  }),
]

/** Completed productions, newest first. */
export const PRODUCTIONS: readonly StubProduction[] = [
  {
    id: 'prod-fixture-launch-film',
    name: 'Kadak Chai launch film',
    orientation: '16:9',
    final_video_url: 'gs://fixture-bucket/productions/prod-fixture-launch-film/final.mp4',
    createdAt: '2026-11-12T12:30:00Z',
  },
  {
    id: 'prod-fixture-festive-teaser',
    name: 'Festive offer teaser',
    orientation: '9:16',
    final_video_url: 'gs://fixture-bucket/productions/prod-fixture-festive-teaser/final.mp4',
    createdAt: '2026-11-10T08:05:00Z',
  },
]

const UPLOADS_BY_ID: ReadonlyMap<string, UploadRecord> = new Map(UPLOADS.map((u) => [u.id, u]))
const PRODUCTIONS_BY_ID: ReadonlyMap<string, StubProduction> = new Map(
  PRODUCTIONS.map((p) => [p.id, p]),
)

export const videoUploads = (): UploadRecord[] => UPLOADS.filter((u) => u.file_type === 'video')

export const findVideoUpload = (id: string): UploadRecord | undefined => {
  const found = UPLOADS_BY_ID.get(id)
  return found?.file_type === 'video' ? found : undefined
}

export const findUpload = (id: string): UploadRecord | undefined => UPLOADS_BY_ID.get(id)

export const findProduction = (id: string): StubProduction | undefined => PRODUCTIONS_BY_ID.get(id)
