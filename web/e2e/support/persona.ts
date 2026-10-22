import { expect, type APIRequestContext, type APIResponse } from '@playwright/test';

/** Сброс персоны сохраняет вход и завершает все действия до ответа (T-372, Q-105). */
export async function resetPersona(request: APIRequestContext, code: string): Promise<void> {
  let response: APIResponse | undefined;
  // «Мои кредиты» может появиться до окончания доставки события в БКИ.
  // Повторяем только 409 по Retry-After: 1; частичный сбой 502 остаётся ошибкой теста.
  await expect
    .poll(
      async () => {
        response = await request.post(`/api/v1/demo/personas/${encodeURIComponent(code)}/reset`);
        return response.status();
      },
      { timeout: 30_000, intervals: [1000], message: `Дождаться завершения операций ${code}` },
    )
    .not.toBe(409);
  if (!response) throw new Error(`Ответ сброса ${code} не получен`);
  if (!response.ok()) {
    throw new Error(
      `Не удалось сбросить ${code}: ${response.status()} ${(await response.text()).slice(0, 300)}`,
    );
  }
}
