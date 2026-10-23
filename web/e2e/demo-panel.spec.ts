import { test, expect } from './fixtures';
import { checkAccessibility } from './support/axe';
import { demo as t } from '../src/texts/demo';

// Своё демо-окружение: общий сброс завершает тест, не затрагивает другие compose-проекты.
test('TS-101: демо-панель: реальная шпаргалка, сбой, восстановление и сброс', async ({
  sessions,
}) => {
  const client = sessions.client;
  await client.goto('/demo');
  const response = await client.request.get('/api/demo/personas');
  expect(response.status()).toBe(200);
  const personas = (await response.json()) as {
    code: string;
    title: string;
    inn: string;
    companyId: string;
  }[];
  const p = personas.find((p) => p.code === 'sokolova');
  expect(p).toBeDefined();
  await expect(client.getByRole('heading', { name: p!.title })).toBeVisible();
  await checkAccessibility(client, 'демо-панель');
  const source = client
    .getByRole('heading', { name: t.systems.tax, exact: true })
    .locator('..')
    .locator('..');
  await source.getByRole('combobox', { name: `${t.chooseMode}: ${t.systems.tax}` }).click();
  await client.getByRole('option', { name: t.modes.DOWN, exact: true }).click();
  await source.getByRole('button', { name: t.set }).click();
  await expect(client.getByText(t.active, { exact: true })).toBeVisible();
  try {
    const [bank] = await Promise.all([
      client.waitForEvent('popup'),
      client.getByRole('button', { name: t.bank, exact: true }).click(),
    ]);
    await expect(bank).toHaveURL(/\/bank/);
    expect((await client.request.get('/api/me')).status()).toBe(200);
    await expect(bank.getByText(t.active, { exact: true })).toBeVisible();
    await bank.getByRole('button', { name: t.open }).click();
    await expect(bank.getByRole('link', { name: t.full })).toBeVisible();
    await checkAccessibility(bank, 'выдвижная демо-панель');
  } finally {
    const r = await client.request.put('/api/demo/chaos/tax', { data: { mode: 'OK' } });
    expect(r.status()).toBe(200);
  }
  await expect(client.getByText(t.active, { exact: true })).toHaveCount(0, { timeout: 15000 });
  const card = client.getByRole('heading', { name: p!.title }).locator('..').locator('..');
  await card.getByRole('button', { name: t.resetOne }).click();
  const modal = client.getByRole('dialog');
  await expect(modal.getByText(t.oneWarning)).toBeVisible();
  await checkAccessibility(client, 'подтверждение сброса');
  await modal.getByRole('button', { name: t.confirm }).click();
  await expect(modal).not.toBeVisible({ timeout: 90000 });
  await expect(client.getByText(t.resetDone, { exact: false })).toBeVisible();
  expect((await client.request.get('/api/me')).status()).toBe(200);
  await client.screenshot({ path: '../docs/screenshots/demo/panel.png', fullPage: true });
  await client.getByRole('button', { name: t.resetAll }).click();
  await client.getByRole('dialog').getByRole('button', { name: t.confirm }).click();
  await expect(client).toHaveURL(/\/login/, { timeout: 90000 });
  expect((await client.request.get('/api/me')).status()).toBe(401);
});
