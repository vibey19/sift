import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Dev only. In production vercel.json rewrites /api/* to the Python function,
  // so the frontend calls the same paths in both environments.
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
