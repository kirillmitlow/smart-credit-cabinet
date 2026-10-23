import { test, expect } from '@playwright/test';
import { demo as t } from '../src/texts/demo';
import { guards } from '../src/texts/shell';

// Проверка браузерной границы: только public-config изменён ответом маршрута.
// Серверные ограничения DEMO_MODE отдельно проверяются интеграционными тестами API.
test('T-434: выключенная демо-панель не загружает свой код по прямому адресу', async ({ page }) => {
  const scripts: string[] = [];
  const demoRequests: string[] = [];
  page.on('request', (r) => {
    if (r.resourceType() === 'script') scripts.push(r.url());
    if (/\/api\/demo\//.test(r.url())) demoRequests.push(r.url());
  });
  await page.route('**/api/public-config', async (route) => {
    const response = await route.fetch();
    const config = (await response.json()) as Record<string, unknown>;
    await route.fulfill({ response, json: { ...config, demoMode: false } });
  });
  await page.goto('/demo');
  await expect(page.getByRole('heading', { name: guards.demoNotFound.title })).toBeVisible();
  await expect(page.getByRole('heading', { name: t.title })).toHaveCount(0);
  await expect(page.getByRole('button', { name: t.open })).toHaveCount(0);
  expect(demoRequests).toEqual([]);
  expect(scripts.filter((url) => /\/(DemoZoneLayout|DemoTools|DemoPanel)[-.]/.test(url))).toEqual(
    [],
  );
});
