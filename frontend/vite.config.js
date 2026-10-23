import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import autoprefixer from 'autoprefixer'
import tailwindcss from 'tailwindcss'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  // Declared here rather than in a separate postcss.config.js: it is four lines
  // of plugin wiring, and Vite is what runs PostCSS. Tailwind's own config stays
  // in tailwind.config.js — that one is 88 lines of design tokens and belongs
  // next to the design system, not inside the build config.
  css: {
    postcss: {
      plugins: [tailwindcss(), autoprefixer()],
    },
  },
  server: {
    port: 5173,
    // Bind on all interfaces so the container is reachable on the Docker network.
    host: true,
    // Mirror the production nginx reverse proxy: /api/* is forwarded to the
    // local backend, so axios can use the same relative `/api` base URL in
    // both dev and prod. Override the target when the backend runs elsewhere.
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    // Half the cores, not all but one. jsdom specs are CPU-bound, and with a
    // worker on every core the heaviest one (PnlSkuTable's 50-row page) took
    // ~10 s on an 8-core laptop and timed out twice in a week; with four
    // workers it takes ~5 s and the whole suite runs 4-6 s longer.
    maxWorkers: '50%',
    // Head-room for a contended machine, not a budget. A one-row table spec
    // that takes 0.15-0.45 s alone once timed out at the 5 s default. A test
    // that gets anywhere near this on an idle box is slow, not unlucky.
    testTimeout: 15_000,
  },
})
