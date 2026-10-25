import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The browser talks to the API through the same origin (/api), so the session
// cookie (HttpOnly, SameSite=Strict) is first-party. In production, the reverse
// proxy in front of the built frontend must route /api to the backend the same way.
const BACKEND = process.env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: BACKEND,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
