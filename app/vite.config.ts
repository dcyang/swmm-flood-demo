import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// The backend (Flask + real SWMM) runs separately; the app reads its base URL
// from VITE_API_BASE (see .env).
//
// To expose the dev server on a public domain, set these in .env:
//   VITE_DEV_HOST=0.0.0.0                  bind all interfaces (default: localhost)
//   VITE_ALLOWED_HOSTS=mydomain.com        Host headers Vite will accept
//   VITE_API_BASE=http://mydomain.com:5057 public address of the backend
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const host = env.VITE_DEV_HOST || '127.0.0.1';
  const allowedHosts = (env.VITE_ALLOWED_HOSTS || 'localhost,127.0.0.1')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

  return {
    plugins: [react()],
    server: {
      host,
      port: 5173,
      strictPort: true,
      allowedHosts,
    },
  };
});
