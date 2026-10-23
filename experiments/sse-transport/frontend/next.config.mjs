/** @type {import('next').NextConfig} */
const nextConfig = {
    compress: process.env.PROBE_DISABLE_NEXT_COMPRESSION !== '1',
    async rewrites() {
        const origin = process.env.SSE_BACKEND_URL ?? 'http://127.0.0.1:18100';
        return [
            {
                source: '/rewrite/:path*',
                destination: `${origin}/stream/:path*`,
            },
        ];
    },
};

export default nextConfig;
