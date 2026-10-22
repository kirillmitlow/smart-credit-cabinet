import { expect, type Locator, type Page } from '@playwright/test';

/** Решение обещано «обычно до минуты» (60-06); ждём с запасом, но без перезагрузки страницы */
export const DECISION_TIMEOUT_MS = 90_000;
/** Выдача после подписи идёт в фоне: несколько секунд, с запасом до минуты */
export const DISBURSEMENT_TIMEOUT_MS = 60_000;

/**
 * Ждём, пока на странице появится нужный элемент, не перезагружая её и без фиксированных пауз.
 * Страница заявки сама обновляется (опрос раз в 3 с или события), поэтому достаточно смотреть на экран.
 * При таймауте в сообщение попадает, что видно на экране сейчас.
 */
export async function waitForStatus(
  page: Page,
  target: Locator,
  description: string,
  timeout = DECISION_TIMEOUT_MS,
): Promise<void> {
  try {
    await expect(target).toBeVisible({ timeout });
  } catch (error) {
    const visible = (
      await page
        .locator('main')
        .innerText()
        .catch(() => '')
    ).replace(/\n+/g, ' | ');
    throw new Error(
      `Не дождались «${description}» за ${timeout / 1000} с без перезагрузки страницы. ` +
        `На экране: ${visible.slice(0, 600)}`,
      { cause: error },
    );
  }
}

const MARKER = '__e2eNoReload';

/**
 * Ставит метку в память страницы. Перезагрузка стирает её, а переходы внутри приложения нет:
 * так проверяем RQ-05 (статус меняется без перезагрузки).
 */
export async function markPageSession(page: Page): Promise<void> {
  await page.evaluate((name) => {
    (window as unknown as Record<string, unknown>)[name] = true;
  }, MARKER);
}

/** Метка на месте: страница с момента `markPageSession` не перезагружалась */
export async function expectNoReload(page: Page): Promise<void> {
  const alive = await page.evaluate(
    (name) => (window as unknown as Record<string, unknown>)[name] === true,
    MARKER,
  );
  expect(alive, 'страница перезагружалась: метка памяти окна пропала (RQ-05)').toBe(true);
}
