/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  eslint: { ignoreDuringBuilds: false },
  typescript: {
    // Fail fast in Docker — keep strict; fixes must be in source
    ignoreBuildErrors: false,
  },
}

module.exports = nextConfig
