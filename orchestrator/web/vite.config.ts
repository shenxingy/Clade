import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  base: '/web/',
  // No publicDir on purpose: web/ is the source tree, not a static root, and
  // copying it wholesale would ship tsconfig/package.json into dist/. The one
  // hand-written page that must still be reachable — usage.html — is served by
  // its own route in server.py (mount_web_ui), declared ahead of the /web mount.
  // Add a file here that the server should serve and it will NOT reach dist/.
  plugins: [
    tailwindcss(),
    react(),
  ],
  server: {
    proxy: {
      '/api': 'http://localhost:8010',
      '/ws': { target: 'ws://localhost:8010', ws: true },
    },
  },
})
