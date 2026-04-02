import { test, expect, Page } from '@playwright/test'

const DIR = './e2e/screenshots'

async function waitForContent(page: Page) {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main')).toBeVisible()
  await page.waitForTimeout(1000)
}

async function snap(page: Page, name: string, anchorId?: string) {
  if (anchorId) {
    await page.locator(`#${anchorId}`).scrollIntoViewIfNeeded()
    await page.waitForTimeout(500)
  }
  await page.screenshot({ path: `${DIR}/${name}.png`, fullPage: false })
}

async function navToFirstCard(page: Page, listPath: string, urlPattern: RegExp, selector = 'button.bg-card') {
  await page.goto(listPath)
  await waitForContent(page)
  await page.waitForTimeout(500)
  await page.locator(selector).first().click()
  await page.waitForURL(urlPattern, { timeout: 10000 })
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(2000)
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

// ── Productions Detail (multi-section) ──────────────────────

test('screenshot: productions-detail', async ({ page }) => {
  await navToFirstCard(page, '/productions', /\/productions\/[^/]/)

  // Hero: video player + header
  await snap(page, 'productions-detail-hero')

  // Production Brief card
  await snap(page, 'productions-detail-brief', 'production-brief')

  // Final Storyboard grid
  await snap(page, 'productions-detail-storyboard', 'final-storyboard')
})

// ── Productions Script ──────────────────────────────────────

test('screenshot: productions-script', async ({ page }) => {
  await navToFirstCard(page, '/productions', /\/productions\/[^/]/)

  // Click "View Technical Script" to navigate to script page
  await page.getByText('View Technical Script').click()
  await page.waitForURL(/\/script/, { timeout: 10000 })
  await waitForContent(page)

  await snap(page, 'productions-script')
})

// ── Key Moments Detail (multi-section) ──────────────────────

test('screenshot: key-moments-detail', async ({ page }) => {
  await navToFirstCard(page, '/key-moments', /\/key-moments\/[^/]/)

  // Video + summary
  await snap(page, 'key-moments-detail-summary', 'video-summary')

  // Key moments list
  await snap(page, 'key-moments-detail-moments', 'key-moments-list')
})

// ── Thumbnails Detail ───────────────────────────────────────

test('screenshot: thumbnails-detail', async ({ page }) => {
  await navToFirstCard(page, '/thumbnails', /\/thumbnails\/[^/]/)
  await snap(page, 'thumbnails-detail', 'screenshots')

  // Generated thumbnail
  await snap(page, 'thumbnails-detail-result', 'generated-thumbnail')
})

// ── Uploads Detail ──────────────────────────────────────────

test('screenshot: uploads-detail', async ({ page }) => {
  await navToFirstCard(page, '/uploads', /\/uploads\/[^/]/, '.grid button')
  await snap(page, 'uploads-detail')
})

// ── Orientations Detail ─────────────────────────────────────

test('screenshot: orientations-detail', async ({ page }) => {
  await navToFirstCard(page, '/orientations', /\/orientations\/[^/]/)
  await snap(page, 'orientations-detail', 'original-video')
})

// ── Promos Detail (multi-section) ───────────────────────────

test('screenshot: promos-detail', async ({ page }) => {
  await navToFirstCard(page, '/promos', /\/promos\/[^/]/)

  // Promo output
  await snap(page, 'promos-detail-output', 'promo-output')

  // Title card + selected moments
  await snap(page, 'promos-detail-titlecard', 'title-card')

  // Selected moments
  await snap(page, 'promos-detail-moments', 'selected-moments')
})

// ── System Prompts Detail ───────────────────────────────────

test('screenshot: system-prompts-detail', async ({ page }) => {
  await navToFirstCard(page, '/prompts', /\/prompts\/[^/]/, 'table button')
  await snap(page, 'system-prompts-detail')
})
