import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs on :8000 (uvicorn airaware.server.app:app); Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { chunkSizeWarningLimit: 900 },
})
