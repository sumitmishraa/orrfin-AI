import type { NextConfig } from 'next';

// The gateway routes /api to the Python API, so Next.js needs no rewrites.
const config: NextConfig = {
  output: 'standalone',
  async redirects() {
    return ['/demo', '/workspace', '/legacy-demo', '/supplier', '/onboarding'].map((source) => ({ source, destination: '/login', permanent: false }));
  },
};

export default config;
