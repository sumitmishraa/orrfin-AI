import type { NextConfig } from 'next';
const config: NextConfig = { distDir: process.env.NEXT_BUILD_DIR || '.next', async headers(){return [{source:'/:path*',headers:[{key:'Referrer-Policy',value:'no-referrer'},{key:'X-Content-Type-Options',value:'nosniff'},{key:'X-Frame-Options',value:'DENY'}]}]}, async rewrites() { const backend = process.env.BACKEND_URL || (process.env.BACKEND_HOSTPORT ? `http://${process.env.BACKEND_HOSTPORT}` : 'http://127.0.0.1:8000'); return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }]; } };
export default config;
