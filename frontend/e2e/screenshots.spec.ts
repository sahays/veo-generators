import { test, expect } from '@playwright/test'

const SCREENSHOT_DIR = './e2e/screenshots'

// Simple list pages
const listPages = [
  { name: 'productions', path: '/productions' },
  { name: 'key-moments', path: '/key-moments' },
  { name: 'thumbnails', path: '/thumbnails' },
  { name: 'uploads', path: '/uploads' },
  { name: 'orientations', path: '/orientations' },
  { name: 'promos', path: '/promos' },
  { name: 'system-prompts', path: '/prompts' },
]

// Create/new pages
const createPages = [
  { name: 'productions-create', path: '/productions/new' },
  { name: 'key-moments-create', path: '/key-moments/analyze' },
  { name: 'thumbnails-create', path: '/thumbnails/create' },
  { name: 'orientations-create', path: '/orientations/create' },
  { name: 'promos-create', path: '/promos/create' },
]

// Detail pages — click the first card on the list page
const detailPages = [
  { name: 'productions-detail', listPath: '/productions', urlPattern: /\/productions\/[^/]/, selector: 'button.bg-card' },
  { name: 'key-moments-detail', listPath: '/key-moments', urlPattern: /\/key-moments\/[^/]/, selector: 'button.bg-card' },
  { name: 'thumbnails-detail', listPath: '/thumbnails', urlPattern: /\/thumbnails\/[^/]/, selector: 'button.bg-card' },
  { name: 'uploads-detail', listPath: '/uploads', urlPattern: /\/uploads\/[^/]/, selector: '.grid button' },
  { name: 'orientations-detail', listPath: '/orientations', urlPattern: /\/orientations\/[^/]/, selector: 'button.bg-card' },
  { name: 'promos-detail', listPath: '/promos', urlPattern: /\/promos\/[^/]/, selector: 'button.bg-card' },
  { name: 'system-prompts-detail', listPath: '/prompts', urlPattern: /\/prompts\/[^/]/, selector: 'table button' },
]

async function screenshot(page: any, name: string) {
  await page.waitForLoadState('networkidle')
  await expect(page.locator('main')).toBeVisible()
  // Allow animations and lazy content to settle
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${SCREENSHOT_DIR}/${name}.png`, fullPage: true })
}

// List views
for (const pg of listPages) {
  test(`screenshot: ${pg.name}`, async ({ page }) => {
    await page.goto(pg.path)
    await screenshot(page, pg.name)
  })
}

// Create views
for (const pg of createPages) {
  test(`screenshot: ${pg.name}`, async ({ page }) => {
    await page.goto(pg.path)
    await screenshot(page, pg.name)
  })
}

// Detail views — navigate to list, click first card
for (const pg of detailPages) {
  test(`screenshot: ${pg.name}`, async ({ page }) => {
    await page.goto(pg.listPath)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(500)

    // Click the first card/item to navigate to detail
    const selector = (pg as any).selector || 'main button, main a[href]'
    const firstCard = page.locator(selector).first()
    await firstCard.click()
    await page.waitForURL(pg.urlPattern, { timeout: 10000 })

    // Wait for detail content to fully load
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    await screenshot(page, pg.name)
  })
}

// Login page (unauthenticated)
test('screenshot: login', async ({ browser, baseURL }) => {
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    baseURL,
  })
  const page = await context.newPage()
  await page.goto('/')
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await page.waitForLoadState('networkidle')
  await expect(page.getByPlaceholder('Enter invite code')).toBeVisible()
  await page.screenshot({ path: `${SCREENSHOT_DIR}/login.png`, fullPage: true })
  await context.close()
})
