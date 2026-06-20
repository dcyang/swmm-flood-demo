import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The backend (Flask + real SWMM) runs separately; the app reads its base URL
// from VITE_API_BASE (see .env), defaulting to the local dev server.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
  },
});
