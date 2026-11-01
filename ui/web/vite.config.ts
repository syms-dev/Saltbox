/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The daemon serves the built app from web/dist; in development Vite proxies
// /api to a local daemon started with `saltbox-uid --no-token`.
const DAEMON = process.env['SALTBOX_UI_DAEMON'] ?? 'http://127.0.0.1:8701';

export default defineConfig({
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        changeOrigin: true,
        target: DAEMON,
        ws: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
});
