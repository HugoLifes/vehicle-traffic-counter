import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// El build produce archivos estáticos que FastAPI sirve tal cual
// (src/api/app.py monta `web/dist`). En el Jetson no corre Node: el
// bundle se construye antes, en la etapa `builder` del Dockerfile.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
  },
  server: {
    port: 5173,
    // En desarrollo el frontend corre en Vite y la API en FastAPI:8000.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
