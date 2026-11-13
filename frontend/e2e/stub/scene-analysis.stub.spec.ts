/**
 * Smoke tests of the Scene Analysis pages against the stub API.
 * Screenshots are written to `e2e/stub/screenshots/`.
 */
import { AD_SPOT_ID, AD_SPOT_RECORD } from '../../src/types/timeline/__tests__/adSpotFixture.ts'
import { PRODUCTIONS, videoUploads } from './data/catalog.ts'
import { expect, test } from './fixtures.ts'

/** Display names of the seeded records, as set in `state.ts`. */
const SEEDED_TITLES = [AD_SPOT_RECORD.display_name ?? '', 'Monsoon drama trailer', 'Festive offer teaser']

test('landing page lists the three seeded analyses', async ({ page, shot, expectNoCrash }) => {
  await page.goto('/scene-analysis')

  const main = page.getByRole('main')
  for (const title of SEEDED_TITLES) {
    await expect(main.getByText(title, { exact: true })).toBeVisible()
  }
  await expectNoCrash()
  await shot('scene-analysis-landing')
})

test('create page lists the stub uploads and productions', async ({ page, shot, expectNoCrash }) => {
  await page.goto('/scene-analysis/new')

  const main = page.getByRole('main')
  for (const upload of videoUploads()) {
    await expect(main.getByText(upload.display_name ?? upload.filename, { exact: true })).toBeVisible()
  }
  await shot('scene-analysis-new-uploads')

  await main.getByRole('button', { name: 'Productions' }).click()
  for (const production of PRODUCTIONS) {
    await expect(main.getByText(production.name, { exact: true })).toBeVisible()
  }
  await expectNoCrash()
  await shot('scene-analysis-new-productions')
})

test('starting an analysis from an upload opens the new record', async ({ page, stub, request }) => {
  await page.goto('/scene-analysis/new')

  const main = page.getByRole('main')
  const upload = videoUploads()[0]
  await main.getByText(upload.display_name ?? upload.filename, { exact: true }).click()
  await main.getByRole('button', { name: 'Start Analysis' }).click()

  // Ids of created records count up from 1 after every reset.
  await expect(page).toHaveURL(/\/scene-analysis\/sa-stub-1$/)
  const created = await request.get(`${stub.origin}/api/v1/scene-analysis/sa-stub-1`)
  expect(await created.json()).toMatchObject({ source_type: 'upload', source_id: upload.id })
})

test('workspace of the completed fixture loads without crashing', async ({ page, shot, expectNoCrash }) => {
  await page.goto(`/scene-analysis/${AD_SPOT_ID}`)

  // Minimal on purpose: the workspace is still being built. Interaction checks go here later.
  await expect(page).toHaveURL(new RegExp(`/scene-analysis/${AD_SPOT_ID}$`))
  await expect(page.getByRole('main')).toBeVisible()
  await page.waitForLoadState('networkidle')
  await expectNoCrash()
  await shot('scene-analysis-workspace')
})
