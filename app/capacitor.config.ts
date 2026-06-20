import type { CapacitorConfig } from '@capacitor/cli';

// Multi-platform shell config. Web is the prototype target (`npm run dev`).
// For native: `npm run build` then `npx cap add android` / `npx cap add ios`,
// then `npx cap sync`. Point `server.url` at your backend host when packaging.
const config: CapacitorConfig = {
  appId: 'kr.seoul.floodswmm',
  appName: '서울 침수 시뮬레이터',
  webDir: 'dist',
  bundledWebRuntime: false,
};

export default config;
