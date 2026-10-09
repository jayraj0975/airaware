import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs on :8000 (uvicorn airaware.server.app:app); Vite proxies /api to it.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    chunkSizeWarningLimit: 400,
    // Libraries in their own files: they change rarely, so browsers keep them cached across app releases.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('leaflet')) return 'map'
          if (id.includes('chart.js') || id.includes('react-chartjs')) return 'charts'
          if (id.includes('react')) return 'react'
          return 'vendor'
        },
      },
    },
  },
})
