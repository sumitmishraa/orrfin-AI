import type { NextConfig } from 'next';
const config: NextConfig = { async rewrites() { const backend = process.env.BACKEND_URL || (process.env.BACKEND_HOSTPORT ? `http://${process.env.BACKEND_HOSTPORT}` : 'http://127.0.0.1:8000'); return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }]; } };
export default config;
