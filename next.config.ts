import type { NextConfig } from 'next';

// The gateway routes /api to the Python API, so Next.js needs no rewrites.
const config: NextConfig = {
  output: 'standalone',
};

export default config;
