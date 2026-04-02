import { test, expect, Page } from '@playwright/test'

const DIR = './e2e/screenshots'

async function waitForContent(page: Page) {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main')).toBeVisible()
  await page.waitForTimeout(1000)
}

async function snap(page: Page, name: string) {
  await page.screenshot({ path: `${DIR}/${name}.png`, fullPage: false })
}

/** Navigate to list, click first card, return the detail page URL path */
async function getFirstDetailPath(page: Page, listPath: string, urlPattern: RegExp, selector = 'button.bg-card') {
  await page.goto(listPath)
  await waitForContent(page)
  await page.waitForTimeout(500)
  await page.locator(selector).first().click()
  await page.waitForURL(urlPattern, { timeout: 10000 })
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(2000)
  return new URL(page.url()).pathname
}

/** Navigate to a detail page anchor URL — uses the app's auto-scroll */
async function gotoAnchor(page: Page, path: string, anchor: string) {
  await page.goto(`${path}#${anchor}`)
  await waitForContent(page)
  // Wait for auto-scroll to complete (app retries up to 10x at 300ms)
  await page.waitForTimeout(3000)
}

// ── List pages ──────────────────────────────────────────────

const listPages = [
  { name: 'productions', path: '/productions' },
  { name: 'key-moments', path: '/key-moments' },
  { name: 'thumbnails', path: '/thumbnails' },
  { name: 'uploads', path: '/uploads' },
  { name: 'orientations', path: '/orientations' },
  { name: 'promos', path: '/promos' },
  { name: 'system-prompts', path: '/prompts' },
]

for (const pg of listPages) {
  test(`screenshot: ${pg.name}`, async ({ page }) => {
    await page.goto(pg.path)
    await waitForContent(page)
    await snap(page, pg.name)
  })
}

// ── Create pages ────────────────────────────────────────────

const createPages = [
  { name: 'productions-create', path: '/productions/new' },
  { name: 'key-moments-create', path: '/key-moments/analyze' },
  { name: 'thumbnails-create', path: '/thumbnails/create' },
  { name: 'orientations-create', path: '/orientations/create' },
  { name: 'promos-create', path: '/promos/create' },
]

for (const pg of createPages) {
  test(`screenshot: ${pg.name}`, async ({ page }) => {
    await page.goto(pg.path)
    await waitForContent(page)
    await snap(page, pg.name)
  })
}

// ── Productions Detail (multi-section via anchor URLs) ──────

test('screenshot: productions-detail', async ({ page }) => {
  const path = await getFirstDetailPath(page, '/productions', /\/productions\/[^/]/)

  // Hero: video player + header (top of page)
  await snap(page, 'productions-detail-hero')

  // Production Brief card
  await gotoAnchor(page, path, 'production-brief')
  await snap(page, 'productions-detail-brief')

  // Final Storyboard grid
  await gotoAnchor(page, path, 'final-storyboard')
  await snap(page, 'productions-detail-storyboard')
})

// ── Productions Script ──────────────────────────────────────

test('screenshot: productions-script', async ({ page }) => {
  const path = await getFirstDetailPath(page, '/productions', /\/productions\/[^/]/)

  await page.goto(`${path}/script`)
  await waitForContent(page)
  await snap(page, 'productions-script')
})

// ── Key Moments Detail (multi-section via anchor URLs) ──────

test('screenshot: key-moments-detail', async ({ page }) => {
  const path = await getFirstDetailPath(page, '/key-moments', /\/key-moments\/[^/]/)

  // Video + summary
  await gotoAnchor(page, path, 'video-summary')
  await snap(page, 'key-moments-detail-summary')

  // Key moments list
  await gotoAnchor(page, path, 'key-moments-list')
  await snap(page, 'key-moments-detail-moments')
})

// ── Thumbnails Detail (multi-section via anchor URLs) ───────

test('screenshot: thumbnails-detail', async ({ page }) => {
  const path = await getFirstDetailPath(page, '/thumbnails', /\/thumbnails\/[^/]/)

  // Screenshots
  await gotoAnchor(page, path, 'screenshots')
  await snap(page, 'thumbnails-detail')

  // Generated thumbnail
  await gotoAnchor(page, path, 'generated-thumbnail')
  await snap(page, 'thumbnails-detail-result')
})

// ── Uploads Detail ──────────────────────────────────────────

test('screenshot: uploads-detail', async ({ page }) => {
  await getFirstDetailPath(page, '/uploads', /\/uploads\/[^/]/, '.grid button')
  await snap(page, 'uploads-detail')
})

// ── Orientations Detail (via anchor URL) ────────────────────

test('screenshot: orientations-detail', async ({ page }) => {
  const path = await getFirstDetailPath(page, '/orientations', /\/orientations\/[^/]/)

  await gotoAnchor(page, path, 'original-video')
  await snap(page, 'orientations-detail')
})

// ── Promos Detail (multi-section via anchor URLs) ───────────

test('screenshot: promos-detail', async ({ page }) => {
  const path = await getFirstDetailPath(page, '/promos', /\/promos\/[^/]/)

  // Promo output
  await gotoAnchor(page, path, 'promo-output')
  await snap(page, 'promos-detail-output')

  // Title card
  await gotoAnchor(page, path, 'title-card')
  await snap(page, 'promos-detail-titlecard')

  // Selected moments
  await gotoAnchor(page, path, 'selected-moments')
  await snap(page, 'promos-detail-moments')
})

// ── System Prompts Detail ───────────────────────────────────

test('screenshot: system-prompts-detail', async ({ page }) => {
  await getFirstDetailPath(page, '/prompts', /\/prompts\/[^/]/, 'table button')
  await snap(page, 'system-prompts-detail')
})
