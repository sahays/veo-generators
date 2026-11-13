import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const rootDir = path.dirname(fileURLToPath(import.meta.url))

// Unit tests cover pure logic only (timeline maths, clock, stores), so they run
// in plain Node without a DOM. Browser behaviour is covered by Playwright (e2e/).
export default defineConfig({
  resolve: {
    alias: { '@': path.resolve(rootDir, 'src') },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
