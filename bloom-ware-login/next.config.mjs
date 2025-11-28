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
}

export default nextConfig
