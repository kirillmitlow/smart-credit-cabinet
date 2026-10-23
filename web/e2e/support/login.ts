import { expect, type Page } from '@playwright/test';
import { fill, home, login } from './text';

/**
 * Вход клиента через интерфейс (D-062, 70-05): ИНН → кто входит → код с экрана → главная.
 * Пользуемся только тем, что видит человек: подписи полей, роли и названия кнопок.
 * Короткий путь `POST /demo/personas/{code}/login` для e2e не годится: он не доказывает вход.
 */
export async function loginAsClient(page: Page, inn: string, personName?: string): Promise<void> {
  await page.goto('/login');
  await page.getByLabel(login.innStep.label).fill(inn);
  await page.getByRole('button', { name: login.innStep.submit }).click();

  // «Кто входит?»: если человек один, он может быть уже выбран; иначе берём первого
  await expect(page.getByRole('heading', { name: login.whoStep.heading })).toBeVisible();
  if (personName) {
    await page.getByRole('radio', { name: new RegExp(personName, 'u') }).check();
  } else if ((await page.getByRole('radio', { checked: true }).count()) === 0) {
    await page.getByRole('radio').first().check();
  }
  await page.getByRole('button', { name: login.whoStep.submit }).click();

  // Код показан на экране текстом «Код: NNNNNN» (демо-режим, D-062)
  const codeLine = page.getByText(
    new RegExp(`^${fill(login.codeStep.demoCode, { code: '\\d{6}' })}$`),
  );
  await expect(codeLine).toBeVisible();
  const code = /\d{6}/.exec((await codeLine.textContent()) ?? '')?.[0];
  if (!code) throw new Error('Код со страницы входа не прочитан: стенд не в демо-режиме?');

  await page.getByLabel(login.codeStep.label).fill(code);
  await page.getByRole('button', { name: login.codeStep.submit }).click();

  await expect(page.getByRole('heading', { level: 1, name: home.title })).toBeVisible();
}

/** Демо-вход банка через интерфейс, со своей cookie sid_bank (T-213, D-085). */
export async function loginAsUnderwriter(page: Page): Promise<void> {
  await page.goto('/login?zone=bank');
  await page.getByRole('button', { name: 'Войти как андеррайтер' }).click();
  await expect(page).toHaveURL(/\/bank$/);
  await expect(page.getByTestId('zone-strip')).toContainText('Рабочее место банка');
}
