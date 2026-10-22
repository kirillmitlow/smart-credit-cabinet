import type { APIRequestContext, TestInfo } from '@playwright/test';

/** Статусы, после которых заявка закрыта; остальные (кроме черновика) держат компанию занятой */
const CLOSED = new Set(['DISBURSED', 'REJECTED', 'WITHDRAWN', 'EXPIRED']);

interface Listed<T> {
  items: T[];
}

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`/api/v1${path}`);
  if (!response.ok()) {
    throw new Error(`GET ${path}: ${response.status()} ${(await response.text()).slice(0, 300)}`);
  }
  return (await response.json()) as T;
}

/**
 * Сброс данных персоны перед тестом (70-05, Q-105: отдельный сброс одной персоны).
 *
 * TODO(T-372): когда появится `POST /demo/personas/{code}/reset`, вызвать его здесь первым делом
 * (после входа, с cookie сессии) и убрать пропуск ниже. До тех пор сбросить персону можно только
 * пересозданием стенда: `docker compose -p scc-pw down -v`, затем `up`. Общий сброс — T-371.
 *
 * Пока сброса нет, функция проверяет, что персона чистая, и пропускает тест с понятным объяснением,
 * если у неё уже есть кредит или заявка в работе: иначе решение будет другим («встречное
 * предложение» из-за платежа по первому кредиту) и тест упал бы по неочевидной причине.
 * Требует, чтобы клиент уже был вошёл (cookie сессии лежит в `request`).
 */
export async function resetPersona(
  request: APIRequestContext,
  code: string,
  info: Pick<TestInfo, 'skip'>,
): Promise<void> {
  // TODO(T-372): await request.post(`/api/v1/demo/personas/${code}/reset`)
  const loans = (await getJson<Listed<{ id: string }>>(request, '/loans')).items;
  const busy = (
    await getJson<Listed<{ number: string; status: string }>>(request, '/applications')
  ).items
    .filter((a) => a.status !== 'DRAFT' && !CLOSED.has(a.status))
    .map((a) => a.number);

  if (loans.length === 0 && busy.length === 0) return;

  const reason =
    `Персона ${code} уже прошла путь (кредитов: ${loans.length}, заявки в работе: ${busy.join(', ') || 'нет'}). ` +
    'Сброса персоны пока нет (T-372): пересоздайте стенд `docker compose -p scc-pw down -v` и поднимите заново.';
  // В CI стенд всегда свежий: грязная персона там — ошибка настройки, а не повод тихо пропустить тест
  if (process.env.CI) throw new Error(reason);
  console.warn(reason);
  info.skip(true, reason);
}
