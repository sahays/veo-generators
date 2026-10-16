import path from 'path'
import { fileURLToPath } from 'url'
import dotenv from 'dotenv'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
dotenv.config({ path: path.resolve(__dirname, '../.env'), quiet: true })

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  outputFileTracingRoot: path.resolve(__dirname),
  experimental: {
    serverActions: {
      bodySizeLimit: '50mb',
    },
  },
  images: {
    unoptimized: true,
  },
  env: {
    NEXT_PUBLIC_GUEST_INVITE_CODE:
      process.env.NEXT_PUBLIC_GUEST_INVITE_CODE ||
      process.env.VITE_GUEST_INVITE_CODE ||
      '',
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
}

export default nextConfig
