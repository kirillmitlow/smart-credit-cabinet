import { defineConfig } from 'orval';

/**
 * Клиент строится из снимка схемы `docs/api/api.openapi.json` (code-first: FastAPI -> снимок, 50-07).
 * Обновить снимок: `curl -s http://127.0.0.1:8100/openapi.json` (api из docker compose), затем `pnpm gen:api`.
 * Руками `src/api/generated/` не правим. CI сверяет, что клиент совпадает со схемой (`pnpm gen:api:check`).
 */
export default defineConfig({
  api: {
    input: { target: '../docs/api/api.openapi.json' },
    output: {
      mode: 'tags-split',
      target: 'src/api/generated/endpoints',
      schemas: 'src/api/generated/model',
      client: 'react-query',
      httpClient: 'fetch',
      clean: true,
      mock: { generators: [{ type: 'msw', delay: 0 }] },
      override: {
        mutator: { path: 'src/api/client.ts', name: 'customFetch' },
      },
    },
  },
});
