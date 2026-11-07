import type { NextConfig } from 'next';

// The gateway routes /api to the Python API, so Next.js needs no rewrites.
const config: NextConfig = {
  output: 'standalone',
  // In `npm run dev`, send /api to the running Docker stack. In production the gateway does this.
  async rewrites() {
    if (process.env.NODE_ENV !== 'development') return [];
    const target = process.env.ORRFIN_API_URL || 'http://localhost:8080';
    return [{ source: '/api/:path*', destination: `${target}/api/:path*` }];
  },
  async redirects() {
    return ['/demo', '/workspace', '/legacy-demo', '/supplier', '/onboarding'].map((source) => ({ source, destination: '/login', permanent: false }));
  },
};

export default config;
