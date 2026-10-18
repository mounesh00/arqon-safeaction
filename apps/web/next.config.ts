import type { NextConfig } from 'next';
const config: NextConfig = { poweredByHeader: false, distDir: process.env.ARQON_VERIFY_BUILD === "1" ? ".next-verify" : ".next", experimental: { cpus: 1 } };
export default config;
