import { describe, expect, it, vi } from 'vitest';
import { appErrorFromResponse, codeFromStatus, parseRetryAfter } from './errors';

describe('codeFromStatus', () => {
  it.each([
    [401, 'UNAUTHENTICATED'],
    [404, 'NOT_FOUND'],
    [409, 'CONFLICT'],
    [422, 'VALIDATION_ERROR'],
    [429, 'RATE_LIMITED'],
    [502, 'SERVICE_UNAVAILABLE'],
    [503, 'SERVICE_UNAVAILABLE'],
    [504, 'SERVICE_UNAVAILABLE'],
    [500, 'UNKNOWN_ERROR'],
    [418, 'UNKNOWN_ERROR'],
  ])('%s → %s', (status, code) => {
    expect(codeFromStatus(status)).toBe(code);
  });
});

describe('parseRetryAfter', () => {
  it('секунды', () => {
    expect(parseRetryAfter('30')).toBe(30);
    expect(parseRetryAfter('0')).toBe(0);
    expect(parseRetryAfter('1.2')).toBe(2);
  });

  it('дата HTTP', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-21T10:00:00Z'));
    expect(parseRetryAfter('Wed, 21 Oct 2026 10:00:45 GMT')).toBe(45);
    expect(parseRetryAfter('Wed, 21 Oct 2026 09:00:00 GMT')).toBe(0);
    vi.useRealTimers();
  });

  it('нет заголовка или мусор', () => {
    expect(parseRetryAfter(null)).toBeNull();
    expect(parseRetryAfter('скоро')).toBeNull();
  });
});

describe('appErrorFromResponse', () => {
  it('разбирает поля в errors[] разных форм и пропускает мусор', () => {
    const error = appErrorFromResponse(
      422,
      {
        code: 'VALIDATION_ERROR',
        errors: [
          { field: 'a', code: 'X', message: 'm' },
          { path: 'b', detail: 'd' },
          { loc: 'c' },
          { message: 'нет пути' },
          'строка',
          null,
        ],
      },
      new Headers(),
      'sent',
    );
    expect(error.errors.map((item) => item.field)).toEqual(['a', 'b', 'c']);
    expect(error.errors[1]?.message).toBe('d');
    expect(error.requestId).toBe('sent');
  });

  it('разбирает loc-массив FastAPI: служебное начало пути отбрасывается', () => {
    const error = appErrorFromResponse(
      422,
      {
        code: 'VALIDATION_ERROR',
        errors: [
          { loc: ['body', 'amountRub'], msg: 'Field required', type: 'missing' },
          { loc: ['body', 'answers', 0, 'x'], msg: 'bad' },
          { loc: [] },
        ],
      },
      new Headers(),
      null,
    );
    expect(error.errors.map((item) => item.field)).toEqual(['amountRub', 'answers.0.x']);
    expect(error.errors[0]).toEqual({
      field: 'amountRub',
      code: 'missing',
      message: 'Field required',
    });
  });

  it('тело не объект → код по статусу', () => {
    const error = appErrorFromResponse(404, 'текст', new Headers(), null);
    expect(error.code).toBe('NOT_FOUND');
    expect(error.requestId).toBeNull();
    expect(error.errors).toEqual([]);
  });
});
