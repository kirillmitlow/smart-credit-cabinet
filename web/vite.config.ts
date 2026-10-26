import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const srcDir = fileURLToPath(new URL('./src', import.meta.url));

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': srcDir } },
  server: {
    port: 5173,
    // Разработка без nginx: /api идёт в api на хосте (docker-compose.override.yml, 127.0.0.1:8100)
    // Как в nginx: префикс /api (и /api/v1) срезается, api слушает пути без него
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api\/(v1\/)?/, '/'),
      },
    },
  },
  // Зона банка и демо подгружаются отдельно (React.lazy в app/router.tsx): отдельные чанки сборки
  build: { sourcemap: false },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/api/generated/**',
        'src/test/**',
        'src/**/*.test.{ts,tsx}',
        'src/main.tsx',
        'src/vite-env.d.ts',
      ],
      thresholds: { lines: 70 },
    },
  },
});
