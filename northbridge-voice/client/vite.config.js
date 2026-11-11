import { defineConfig } from 'vite';

// In dev, /api goes to the FastAPI server so the browser stays same-origin.
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
