import { expect, test } from '@playwright/test';
import { checkAccessibility } from './support/axe';
import { loginAsClient } from './support/login';
import { personas } from './support/personas';
import { home, shell } from './support/text';

// Пример-тест обвязки (T-518): вход по ИНН через интерфейс и главная демо-персоны.
// Состояние персоны не трогает, поэтому идёт на любом стенде, в том числе после TS-001.
test('вход Соколовой по ИНН и коду с экрана показывает главную', async ({ page }) => {
  await loginAsClient(page, personas.sokolova.inn);

  await expect(page.getByRole('heading', { level: 1, name: home.title })).toBeVisible();
  await expect(page.getByText(shell.demoBanner)).toBeVisible();
  await expect(page.getByRole('link', { name: shell.nav.wizard }).first()).toBeVisible();
  await checkAccessibility(page, 'Главная');
});
