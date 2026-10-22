/**
 * Общий обработчик запросов (T-402, 60-01 «Слой API»). Единственное место с `fetch`.
 *
 * Добавляет служебные заголовки:
 * - `X-Request-Id`: новый на каждый запрос (сквозной номер для поддержки);
 * - `X-CSRF-Token`: из cookie, для всех методов кроме GET/HEAD/OPTIONS;
 * - `Idempotency-Key`: передаёт вызывающий (см. `useActionKey`), здесь только не затираем.
 * Любую ошибку превращает в `AppError`.
 */
import { newId } from '@/lib/id';
import { AppError, NETWORK_ERROR, appErrorFromResponse } from './errors';
import { currentZone, type Zone } from './zone';

/** Все адреса api идут через тот же origin под `/api` (nginx проксирует, CORS не нужен) */
export const API_PREFIX = '/api';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** Имя cookie с токеном CSRF по зоне (по аналогии с sid_client / sid_bank, Q-146) */
export function csrfCookieName(zone: Zone): string {
  return `csrf_${zone}`;
}

export function readCookie(name: string): string | null {
  for (const part of document.cookie.split(';')) {
    const [rawName, ...rest] = part.trim().split('=');
    if (rawName === name) return decodeURIComponent(rest.join('='));
  }
  return null;
}

/** Сгенерированные пути (`/health/live`) получают префикс `/api`; пути с `/api/…` не трогаем */
export function resolveUrl(url: string): string {
  if (/^https?:\/\//.test(url)) return url;
  if (url === API_PREFIX || url.startsWith(`${API_PREFIX}/`)) return url;
  return `${API_PREFIX}${url.startsWith('/') ? '' : '/'}${url}`;
}

export interface ApiResponse<T> {
  data: T;
  status: number;
  headers: Headers;
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return undefined;
  const text = await response.text();
  if (text === '') return undefined;
  const type = response.headers.get('Content-Type') ?? '';
  if (type.includes('json')) {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return undefined;
    }
  }
  return text;
}

/** Выполняет запрос; не-2xx и сбои сети бросают AppError */
export async function request<T>(url: string, options: RequestInit = {}): Promise<ApiResponse<T>> {
  const method = (options.method ?? 'GET').toUpperCase();
  const headers = new Headers(options.headers);
  const requestId = newId();
  headers.set('X-Request-Id', requestId);
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  if (!SAFE_METHODS.has(method) && !headers.has('X-CSRF-Token')) {
    const token = readCookie(csrfCookieName(currentZone()));
    if (token) headers.set('X-CSRF-Token', token);
  }

  let response: Response;
  try {
    response = await fetch(resolveUrl(url), {
      credentials: 'same-origin',
      ...options,
      method,
      headers,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new AppError({ code: NETWORK_ERROR, status: 0, requestId });
  }

  const body = await readBody(response);
  if (!response.ok) {
    throw appErrorFromResponse(response.status, body, response.headers, requestId);
  }
  return { data: body as T, status: response.status, headers: response.headers };
}

/**
 * Мутатор orval (`orval.config.ts`): сгенерированные хуки зовут именно его.
 * Тип результата совпадает с обёрткой `{ data, status, headers }`, которую строит orval.
 */
export async function customFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  return (await request<unknown>(url, options)) as T;
}

/** Для ручек, которых ещё нет в схеме (`/me`, `/public-config`): возвращает только тело ответа */
export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const options: RequestInit = signal ? { signal } : {};
  return (await request<T>(path, options)).data;
}
