import { test, expect } from '@playwright/test'

const SCREENSHOT_DIR = './e2e/screenshots'

const pages = [
  { name: 'productions', path: '/productions', title: 'Productions' },
  { name: 'new-production', path: '/productions/new', title: 'New Production' },
  { name: 'key-moments', path: '/key-moments', title: 'Key Moments' },
  { name: 'thumbnails', path: '/thumbnails', title: 'Thumbnails' },
  { name: 'uploads', path: '/uploads', title: 'Files' },
  { name: 'orientations', path: '/orientations', title: 'Orientations' },
  { name: 'promos', path: '/promos', title: 'Promos' },
  { name: 'system-prompts', path: '/prompts', title: 'System Prompts' },
  { name: 'diagnostics', path: '/diagnostics', title: 'Diagnostics' },
  { name: 'invite-codes', path: '/invite-codes', title: 'Invite Codes' },
]

for (const pg of pages) {
  test(`screenshot: ${pg.name}`, async ({ page }) => {
    await page.goto(pg.path)
    // Wait for page content to settle
    await page.waitForLoadState('networkidle')
    await expect(page.locator('main')).toBeVisible()

    await page.screenshot({
      path: `${SCREENSHOT_DIR}/${pg.name}.png`,
      fullPage: true,
    })
  })
}

test('screenshot: login page', async ({ browser, baseURL }) => {
  // Use a fresh context without auth state to capture the login gate
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    baseURL,
  })
  const page = await context.newPage()

  // Navigate and clear any cached auth before the app reads localStorage
  await page.goto('/')
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await page.waitForLoadState('networkidle')
  await expect(page.getByPlaceholder('Enter invite code')).toBeVisible()

  await page.screenshot({
    path: `${SCREENSHOT_DIR}/login.png`,
    fullPage: true,
  })

  await context.close()
})
