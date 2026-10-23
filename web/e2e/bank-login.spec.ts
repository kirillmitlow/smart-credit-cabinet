import { test, expect } from '@playwright/test';
import { loginAsClient, loginAsUnderwriter } from './support/login';
import { home } from './support/text';
import { personas } from './support/personas';
import { logout } from '../src/texts';

test('T-213: клиент и андеррайтер входят и выходят независимо в одном браузере', async ({
  page,
  context,
}) => {
  await loginAsClient(page, personas.sokolova.inn);
  const initialClient = (await (await page.request.get('/api/v1/me')).json()) as { userId: string };
  const bank = await context.newPage();
  await loginAsUnderwriter(bank);
  const employee = (await (await bank.request.get('/api/v1/auth/bank-me')).json()) as {
    role: string;
    level: string;
  };
  expect(employee.role).toBe('UNDERWRITER');
  expect(employee.level).toBe('L2');
  const unchangedClient = (await (await page.request.get('/api/v1/me')).json()) as {
    userId: string;
  };
  expect(unchangedClient.userId).toBe(initialClient.userId);
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: home.title })).toBeVisible();
  expect((await page.request.post('/api/v1/auth/logout')).status()).toBe(204);
  expect((await bank.request.get('/api/v1/auth/bank-me')).status()).toBe(200);
  await loginAsClient(page, personas.sokolova.inn);
  await bank.getByRole('button', { name: logout.action }).click();
  await expect(bank).toHaveURL(/\/login\?zone=bank$/);
  expect((await bank.request.get('/api/v1/auth/bank-me')).status()).toBe(401);
  expect((await page.request.get('/api/v1/me')).status()).toBe(200);
});
