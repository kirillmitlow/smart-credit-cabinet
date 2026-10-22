import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { problemResponse } from '@/test/factories';
import { server } from '@/test/server';
import { apiGet, request, resolveUrl } from './client';
import { AppError, isAppError, toAppError } from './errors';

async function caught(promise: Promise<unknown>): Promise<AppError> {
  try {
    await promise;
  } catch (error) {
    if (isAppError(error)) return error;
    throw error;
  }
  throw new Error('Ожидалась ошибка, запрос прошёл');
}

describe('resolveUrl', () => {
  it('путь без /api получает префикс', () => {
    expect(resolveUrl('/health/live')).toBe('/api/health/live');
    expect(resolveUrl('health/live')).toBe('/api/health/live');
  });

  it('путь с /api не меняется', () => {
    expect(resolveUrl('/api/v1/me')).toBe('/api/v1/me');
    expect(resolveUrl('/api')).toBe('/api');
  });

  it('полный адрес не меняется', () => {
    expect(resolveUrl('http://localhost/x')).toBe('http://localhost/x');
  });
});

describe('служебные заголовки', () => {
  it('X-Request-Id новый на каждый запрос', async () => {
    const ids: (string | null)[] = [];
    server.use(
      http.get('*/api/v1/ping', ({ request: req }) => {
        ids.push(req.headers.get('X-Request-Id'));
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiGet('/api/v1/ping');
    await apiGet('/api/v1/ping');
    expect(ids).toHaveLength(2);
    expect(ids[0]).toBeTruthy();
    expect(ids[1]).toBeTruthy();
    expect(ids[0]).not.toBe(ids[1]);
  });

  it('X-CSRF-Token берётся из cookie и уходит только на не-GET', async () => {
    document.cookie = 'csrf_client=token-123; path=/';
    const seen: Record<string, string | null> = {};
    server.use(
      http.get('*/api/v1/thing', ({ request: req }) => {
        seen.get = req.headers.get('X-CSRF-Token');
        return HttpResponse.json({});
      }),
      http.post('*/api/v1/thing', ({ request: req }) => {
        seen.post = req.headers.get('X-CSRF-Token');
        return HttpResponse.json({});
      }),
    );
    await request('/api/v1/thing');
    await request('/api/v1/thing', { method: 'POST', body: '{}' });
    expect(seen.get).toBeNull();
    expect(seen.post).toBe('token-123');
  });

  it('в зоне банка берётся cookie банка', async () => {
    window.history.pushState({}, '', '/bank');
    document.cookie = 'csrf_client=client-token; path=/';
    document.cookie = 'csrf_bank=bank-token; path=/';
    let token: string | null = null;
    server.use(
      http.post('*/api/v1/thing', ({ request: req }) => {
        token = req.headers.get('X-CSRF-Token');
        return HttpResponse.json({});
      }),
    );
    await request('/api/v1/thing', { method: 'POST', body: '{}' });
    expect(token).toBe('bank-token');
  });

  it('Idempotency-Key, переданный вызывающим, не затирается', async () => {
    let key: string | null = null;
    server.use(
      http.post('*/api/v1/thing', ({ request: req }) => {
        key = req.headers.get('Idempotency-Key');
        return HttpResponse.json({});
      }),
    );
    await request('/api/v1/thing', { method: 'POST', headers: { 'Idempotency-Key': 'k-1' } });
    expect(key).toBe('k-1');
  });

  it('возвращает {data, status, headers} как ждёт orval', async () => {
    server.use(http.get('*/api/v1/ping', () => HttpResponse.json({ ok: true }, { status: 200 })));
    const response = await request<{ ok: boolean }>('/api/v1/ping');
    expect(response.status).toBe(200);
    expect(response.data).toEqual({ ok: true });
    expect(response.headers.get('content-type')).toContain('json');
  });

  it('ответ без тела (204) не ломает разбор', async () => {
    server.use(http.post('*/api/v1/thing', () => new HttpResponse(null, { status: 204 })));
    const response = await request('/api/v1/thing', { method: 'POST' });
    expect(response.status).toBe(204);
    expect(response.data).toBeUndefined();
  });
});

describe('ошибки превращаются в AppError', () => {
  it('problem+json: code, status, requestId, errors[]', async () => {
    server.use(
      http.post('*/api/v1/applications', () =>
        problemResponse({
          status: 422,
          code: 'VALIDATION_ERROR',
          requestId: 'req-42',
          errors: [{ field: 'company.inn', code: 'INN_INVALID', message: 'Неверный ИНН' }],
        }),
      ),
    );
    const error = await caught(request('/api/v1/applications', { method: 'POST' }));
    expect(error).toBeInstanceOf(AppError);
    expect(error.code).toBe('VALIDATION_ERROR');
    expect(error.status).toBe(422);
    expect(error.requestId).toBe('req-42');
    expect(error.errors).toEqual([
      { field: 'company.inn', code: 'INN_INVALID', message: 'Неверный ИНН' },
    ]);
  });

  it('401 → UNAUTHENTICATED', async () => {
    server.use(
      http.get('*/api/v1/me', () => problemResponse({ status: 401, code: 'UNAUTHENTICATED' })),
    );
    const error = await caught(apiGet('/api/v1/me'));
    expect(error.status).toBe(401);
    expect(error.code).toBe('UNAUTHENTICATED');
  });

  it('409 VERSION_CONFLICT', async () => {
    server.use(
      http.patch('*/api/v1/applications/1/draft', () =>
        problemResponse({ status: 409, code: 'VERSION_CONFLICT' }),
      ),
    );
    const error = await caught(request('/api/v1/applications/1/draft', { method: 'PATCH' }));
    expect(error.status).toBe(409);
    expect(error.code).toBe('VERSION_CONFLICT');
  });

  it('429 с Retry-After', async () => {
    server.use(
      http.get('*/api/v1/x', () =>
        problemResponse({ status: 429, code: 'RATE_LIMITED', headers: { 'Retry-After': '17' } }),
      ),
    );
    const error = await caught(apiGet('/api/v1/x'));
    expect(error.code).toBe('RATE_LIMITED');
    expect(error.retryAfterSeconds).toBe(17);
  });

  it('503 SERVICE_UNAVAILABLE', async () => {
    server.use(
      http.get('*/api/v1/x', () => problemResponse({ status: 503, code: 'SERVICE_UNAVAILABLE' })),
    );
    const error = await caught(apiGet('/api/v1/x'));
    expect(error.status).toBe(503);
    expect(error.code).toBe('SERVICE_UNAVAILABLE');
  });

  it('неизвестный code не роняет: AppError с тем же кодом', async () => {
    server.use(http.get('*/api/v1/x', () => problemResponse({ status: 418, code: 'TEAPOT_NEW' })));
    const error = await caught(apiGet('/api/v1/x'));
    expect(error.code).toBe('TEAPOT_NEW');
  });

  it('ответ nginx без problem+json (HTML 502) → SERVICE_UNAVAILABLE', async () => {
    server.use(
      http.get(
        '*/api/v1/x',
        () =>
          new HttpResponse('<html>502 Bad Gateway</html>', {
            status: 502,
            headers: { 'Content-Type': 'text/html' },
          }),
      ),
    );
    const error = await caught(apiGet('/api/v1/x'));
    expect(error.code).toBe('SERVICE_UNAVAILABLE');
    expect(error.status).toBe(502);
    expect(error.requestId).toBeTruthy();
  });

  it('тело не JSON при статусе 500 → UNKNOWN_ERROR', async () => {
    server.use(http.get('*/api/v1/x', () => new HttpResponse('boom', { status: 500 })));
    const error = await caught(apiGet('/api/v1/x'));
    expect(error.code).toBe('UNKNOWN_ERROR');
  });

  it('обрыв сети → NETWORK_ERROR со статусом 0 и номером запроса', async () => {
    server.use(http.get('*/api/v1/x', () => HttpResponse.error()));
    const error = await caught(apiGet('/api/v1/x'));
    expect(error.code).toBe('NETWORK_ERROR');
    expect(error.status).toBe(0);
    expect(error.requestId).toBeTruthy();
  });

  it('requestId берётся из заголовка ответа, если в теле его нет', async () => {
    server.use(
      http.get('*/api/v1/x', () =>
        HttpResponse.json(
          { code: 'NOT_FOUND' },
          { status: 404, headers: { 'X-Request-Id': 'from-header' } },
        ),
      ),
    );
    const error = await caught(apiGet('/api/v1/x'));
    expect(error.requestId).toBe('from-header');
  });
});

describe('toAppError', () => {
  it('любое исключение становится AppError', () => {
    expect(toAppError(new Error('x')).code).toBe('UNKNOWN_ERROR');
    expect(toAppError('строка').code).toBe('UNKNOWN_ERROR');
    const original = new AppError({ code: 'NOT_FOUND', status: 404, requestId: null });
    expect(toAppError(original)).toBe(original);
  });
});
