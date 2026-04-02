import { test as setup, expect } from '@playwright/test'

const MASTER_CODE = process.env.MASTER_INVITE_CODE!

setup('authenticate with master invite code', async ({ page }) => {
  await page.goto('/')

  // Fill in the invite code and submit
  await page.getByPlaceholder('Enter invite code').fill(MASTER_CODE)
  await page.getByRole('button', { name: /continue/i }).click()

  // Wait for redirect to productions page (authenticated)
  await expect(page).toHaveURL(/\/productions/, { timeout: 10000 })

  // Save auth state (localStorage) for reuse by other tests
  await page.context().storageState({ path: './e2e/.auth/storage-state.json' })
})
