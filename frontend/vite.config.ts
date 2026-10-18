import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    // Same origin for the API and the prototype iframe (contracts/conventions.md).
    proxy: { '/api': 'http://localhost:8000' },
    // Mocks import ../contracts/fixtures/api/ directly.
    fs: { allow: ['..'] },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.{ts,tsx}'],
    env: { VITE_MOCK: '1' },
  },
});
