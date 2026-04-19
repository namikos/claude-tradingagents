/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The state directory lives one level above the Next.js app root.
  // We add it (and chokidar) to the server external packages so they're
  // not bundled by webpack.
  serverExternalPackages: ['chokidar'],
  experimental: {
    // Allow filesystem reads outside the Next workspace.
    outputFileTracingRoot: undefined,
  },
};

export default nextConfig;
