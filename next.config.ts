import type { NextConfig } from 'next';

// Docker: the Caddy gateway routes /api to the Python API. Vercel: set ORRFIN_API_URL to a hosted
// backend and /api is proxied there (same origin, so the session cookie stays first-party).
// DEMO_BACKEND is the hackathon demo stack, reached through a temporary tunnel; ORRFIN_API_URL overrides it.
const DEMO_BACKEND = 'https://0157b207e2eaa1.lhr.life';
const apiTarget = process.env.ORRFIN_API_URL
  || (process.env.VERCEL ? DEMO_BACKEND : process.env.NODE_ENV === 'development' ? 'http://localhost:8080' : '');

const config: NextConfig = {
  output: process.env.VERCEL ? undefined : 'standalone',
  async rewrites() {
    if (!apiTarget) return [];
    return [{ source: '/api/:path*', destination: `${apiTarget.replace(/\/$/, '')}/api/:path*` }];
  },
  async redirects() {
    return ['/workspace', '/legacy-demo', '/supplier', '/onboarding'].map((source) => ({ source, destination: '/login', permanent: false }));
  },
};

export default config;
