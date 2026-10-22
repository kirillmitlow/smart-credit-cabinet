import { describe, expect, it } from 'vitest';
import { AppError } from '@/api/errors';
import {
  applicationStatusLabels,
  emptyStates,
  errorTexts,
  errorView,
  fill,
  guards,
  loginPlaceholder,
  needsHelpStep,
  placeholders,
  shell,
  termHints,
  timelineNotes,
  timelineSteps,
  demoMarks,
  otherErrors,
  login,
  companyChoice,
  logout,
  home,
  productNames,
  applicationForm,
  consents,
  applicationPage,
  outcomes,
  wizard,
  wizardResult,
  variantCard,
} from '.';
import { forbiddenClientWords } from './forbidden';

/** Все строки словаря (значения), кроме шаблонов подстановки */
function collectStrings(value: unknown, into: string[] = []): string[] {
  if (typeof value === 'string') into.push(value);
  else if (Array.isArray(value)) value.forEach((item) => collectStrings(item, into));
  else if (value && typeof value === 'object') {
    Object.values(value).forEach((item) => collectStrings(item, into));
  }
  return into;
}

const allTexts = collectStrings([
  errorTexts,
  otherErrors,
  shell,
  guards,
  loginPlaceholder,
  placeholders,
  timelineSteps,
  needsHelpStep,
  timelineNotes,
  applicationStatusLabels,
  emptyStates,
  termHints,
  demoMarks,
  login,
  companyChoice,
  logout,
  home,
  productNames,
  applicationForm,
  consents,
  applicationPage,
  outcomes,
  wizard,
  wizardResult,
  variantCard,
]);

describe('словарь текстов', () => {
  it('не пустой и без пустых строк', () => {
    expect(allTexts.length).toBeGreaterThan(100);
    expect(allTexts.every((text) => text.trim() !== '')).toBe(true);
  });

  it.each(forbiddenClientWords)('в клиентских текстах нет слова «$label»', ({ pattern }) => {
    const hits = allTexts.filter((text) => pattern.test(text));
    expect(hits).toEqual([]);
  });

  it('тест запрещённых слов действительно ловит слова', () => {
    const sample =
      'Аннуитетный платёж, обеспечение, кассовый разрыв, цель кредитования, грейд, скоринг, DSCR, стоп-фактор';
    for (const { pattern } of forbiddenClientWords) {
      expect(pattern.test(sample)).toBe(true);
    }
  });

  it('каждый код ошибки из 50-07 имеет текст', () => {
    const codes = [
      'BAD_REQUEST',
      'INN_INVALID',
      'UNAUTHENTICATED',
      'ROLE_CANNOT_SIGN',
      'DEMO_MODE_DISABLED',
      'NOT_FOUND',
      'INVALID_TRANSITION',
      'VERSION_CONFLICT',
      'DUPLICATE_APPLICATION',
      'IDEMPOTENCY_IN_PROGRESS',
      'IDEMPOTENCY_KEY_REUSED',
      'VALIDATION_ERROR',
      'CONSENT_REQUIRED',
      'RATE_LIMITED',
      'SERVICE_UNAVAILABLE',
    ];
    for (const code of codes) {
      expect(errorTexts).toHaveProperty(code);
    }
  });

  it('все статусы заявки из 20-02 названы', () => {
    expect(Object.keys(applicationStatusLabels)).toEqual([
      'DRAFT',
      'SUBMITTED',
      'CHECKING',
      'NEEDS_INFO',
      'MANUAL_REVIEW',
      'APPROVED',
      'COUNTER_OFFER',
      'OFFER_ACCEPTED',
      'SIGNED',
      'DISBURSING',
      'DISBURSED',
      'REJECTED',
      'WITHDRAWN',
      'EXPIRED',
    ]);
  });

  it('шесть шагов таймлайна', () => {
    expect(timelineSteps).toHaveLength(6);
  });
});

describe('fill', () => {
  it('подставляет значения', () => {
    expect(fill('Код: {requestId}, осталось {n}', { requestId: 'r-1', n: 2 })).toBe(
      'Код: r-1, осталось 2',
    );
  });

  it('неизвестное имя остаётся как есть', () => {
    expect(fill('Привет, {name}', {})).toBe('Привет, {name}');
  });
});

describe('errorView', () => {
  it('известный код → текст и кнопка из словаря, а не detail сервера', () => {
    const view = errorView(
      new AppError({
        code: 'VERSION_CONFLICT',
        status: 409,
        requestId: 'req-1',
        detail: 'row version mismatch (для разработчика)',
      }),
    );
    expect(view.text).toBe(errorTexts.VERSION_CONFLICT.text);
    expect(view.action).toBe(errorTexts.VERSION_CONFLICT.action);
    expect(view.requestId).toBe('req-1');
    expect(view.text).not.toContain('row version');
  });

  it('неизвестный код → общий текст и номер запроса', () => {
    const view = errorView(
      new AppError({ code: 'SOMETHING_NEW', status: 418, requestId: 'req-9' }),
    );
    expect(view.text).toBe(errorTexts.UNKNOWN_ERROR.text);
    expect(view.requestId).toBe('req-9');
    expect(view.code).toBe('SOMETHING_NEW');
  });

  it('служебные имена объекта не считаются кодами', () => {
    const view = errorView(new AppError({ code: 'toString', status: 500, requestId: null }));
    expect(view.text).toBe(errorTexts.UNKNOWN_ERROR.text);
  });

  it('не AppError → общий текст', () => {
    expect(errorView(new Error('boom')).text).toBe(errorTexts.UNKNOWN_ERROR.text);
    expect(errorView('что угодно').text).toBe(errorTexts.UNKNOWN_ERROR.text);
    expect(errorView(undefined).requestId).toBeNull();
  });

  it('429 с Retry-After называет секунды', () => {
    const view = errorView(
      new AppError({ code: 'RATE_LIMITED', status: 429, requestId: 'r', retryAfterSeconds: 30 }),
    );
    expect(view.text).toContain('30');
    expect(view.text).toContain('секунд');
  });

  it('429 без Retry-After — «подождите минуту»', () => {
    const view = errorView(new AppError({ code: 'RATE_LIMITED', status: 429, requestId: 'r' }));
    expect(view.text).toBe(errorTexts.RATE_LIMITED.text);
  });
});
