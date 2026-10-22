/**
 * Единый тип ошибки приложения (60-01, «Слой API», п. 4).
 * Любая ошибка сервера или сети превращается в AppError: экраны смотрят на `code`,
 * а текст для человека берут из словаря `texts/` (а не из `detail`).
 */

export interface FieldError {
  /** Путь к полю, например `company.inn` */
  field: string;
  code: string | null;
  message: string | null;
}

export interface AppErrorInit {
  code: string;
  status: number;
  requestId: string | null;
  errors?: FieldError[];
  retryAfterSeconds?: number | null;
  title?: string | null;
  detail?: string | null;
}

/** Код, который ставим сами, когда сервер не прислал problem+json (сеть, nginx 502 и т.п.) */
export const NETWORK_ERROR = 'NETWORK_ERROR';
export const UNKNOWN_ERROR = 'UNKNOWN_ERROR';

export class AppError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | null;
  readonly errors: FieldError[];
  readonly retryAfterSeconds: number | null;
  readonly title: string | null;
  readonly detail: string | null;

  constructor(init: AppErrorInit) {
    super(init.detail ?? init.title ?? init.code);
    this.name = 'AppError';
    this.code = init.code;
    this.status = init.status;
    this.requestId = init.requestId;
    this.errors = init.errors ?? [];
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
    this.title = init.title ?? null;
    this.detail = init.detail ?? null;
  }
}

export function isAppError(value: unknown): value is AppError {
  return value instanceof AppError;
}

/** Любое исключение → AppError (неизвестное не роняет приложение) */
export function toAppError(value: unknown): AppError {
  if (isAppError(value)) return value;
  return new AppError({
    code: UNKNOWN_ERROR,
    status: 0,
    requestId: null,
    detail: value instanceof Error ? value.message : null,
  });
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function parseFieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) return [];
  const result: FieldError[] = [];
  for (const item of value as unknown[]) {
    const record = asRecord(item);
    if (!record) continue;
    const field = asString(record.field) ?? asString(record.path) ?? asString(record.loc);
    if (!field) continue;
    result.push({
      field,
      code: asString(record.code),
      message: asString(record.message) ?? asString(record.detail),
    });
  }
  return result;
}

/** Код по статусу HTTP, когда тела problem+json нет */
export function codeFromStatus(status: number): string {
  switch (status) {
    case 401:
      return 'UNAUTHENTICATED';
    case 404:
      return 'NOT_FOUND';
    case 409:
      return 'CONFLICT';
    case 422:
      return 'VALIDATION_ERROR';
    case 429:
      return 'RATE_LIMITED';
    case 502:
    case 503:
    case 504:
      return 'SERVICE_UNAVAILABLE';
    default:
      return UNKNOWN_ERROR;
  }
}

export function parseRetryAfter(header: string | null): number | null {
  if (header === null) return null;
  const seconds = Number(header);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.ceil(seconds);
  const date = Date.parse(header);
  if (Number.isNaN(date)) return null;
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
}

/** Разбирает ответ с ошибкой (problem+json, 50-07) в AppError */
export function appErrorFromResponse(
  status: number,
  body: unknown,
  headers: Headers,
  sentRequestId: string | null,
): AppError {
  const problem = asRecord(body);
  return new AppError({
    code: asString(problem?.code) ?? codeFromStatus(status),
    status,
    requestId: asString(problem?.requestId) ?? headers.get('X-Request-Id') ?? sentRequestId,
    errors: parseFieldErrors(problem?.errors),
    retryAfterSeconds: parseRetryAfter(headers.get('Retry-After')),
    title: asString(problem?.title),
    detail: asString(problem?.detail),
  });
}
