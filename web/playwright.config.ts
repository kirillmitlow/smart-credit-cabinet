import { defineConfig, devices } from '@playwright/test';

/**
 * Сквозные тесты в браузере (T-518, 70-05). Идут против поднятого стенда, сами его не поднимают:
 *   WEB_PORT=8088 docker compose -p scc-pw up -d --build --wait
 *   E2E_BASE_URL=http://localhost:8088 pnpm e2e
 * Без E2E_BASE_URL берётся http://localhost:8080 (порт compose по умолчанию).
 */
const isCi = Boolean(process.env.CI);

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  outputDir: './test-results',
  // Один повтор только в CI; локально падение должно быть видно сразу
  retries: isCi ? 1 : 0,
  forbidOnly: isCi,
  // Персоны ходят разными компаниями, но сброса одной персоны пока нет (T-371, T-372),
  // а общий стенд один: идём одним потоком
  workers: 1,
  fullyParallel: false,
  // Весь путь Соколовой: вход, заявка, решение до 90 с, подпись, выдача
  timeout: 240_000,
  expect: { timeout: 10_000 },
  reporter: isCi
    ? [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]]
    : [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    // Трасса, видео и скриншот остаются только у упавших тестов
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      testIgnore: '**/chaos/**',
      use: { ...devices['Desktop Chrome'] },
    },
    {
      // Хаос-тесты (70-06): роняют моки, worker и redis, поэтому идут после остальных
      // и строго по одному. Заготовка: сценариев пока нет, папка e2e/chaos/ пуста
      name: 'chaos',
      testMatch: '**/chaos/**/*.spec.ts',
      dependencies: ['chromium'],
      fullyParallel: false,
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
