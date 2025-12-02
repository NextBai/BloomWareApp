import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

/** @type {import('next').NextConfig} */
const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  output: 'export',
  basePath: '/login',  // 所有靜態資源路徑加上 /login 前綴
  distDir: 'out',
  trailingSlash: true,
  turbopack: {
    resolveAlias: {
      '@': __dirname,
    },
  },
}

export default nextConfig
