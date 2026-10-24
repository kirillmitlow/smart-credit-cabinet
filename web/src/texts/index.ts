/**
 * Словарь текстов интерфейса (T-405, 60-06). Все пользовательские строки лежат здесь:
 * ключи типизированы, подстановки — `{имя}`. Экраны и тесты берут тексты отсюда, не копируют.
 */
import { formatSeconds } from '@/lib/format';
import { isAppError, toAppError, type AppError } from '@/api/errors';
import { errorTexts, genericError, retryAfterText, type ErrorText } from './errors';
import { productNames } from './application';

export {
  errorTexts,
  otherErrors,
  supportCodeLabel,
  copySupportCode,
  supportCodeCopied,
} from './errors';
export type { ErrorText, KnownErrorCode } from './errors';
export { shell, guards, loginPlaceholder, placeholders } from './shell';
export {
  timelineSteps,
  needsHelpStep,
  timelineNotes,
  timelineProgress,
  applicationStatusLabels,
} from './timeline';
export type { ApplicationStatus } from './timeline';
export { emptyStates, termHints, demoMarks } from './content';
export { login, companyChoice, logout } from './login';
export { home } from './home';
export { loansTexts } from './loans';
export { catalogTexts } from './catalog';
export { decision } from './decision';
export { consents } from './consents';
export { wizard, wizardResult, variantCard } from './wizard';
export { productNames, applicationForm, applicationPage, outcomes } from './application';
export { counterOffer } from './counterOffer';
export { clientTasks } from './clientTasks';

/** Название продукта по коду; неизвестный код показываем как есть, чтобы не терять данные */
export function productName(code: string | null | undefined): string | null {
  if (!code) return null;
  return Object.prototype.hasOwnProperty.call(productNames, code)
    ? productNames[code as keyof typeof productNames]
    : code;
}

/**
 * Как `fill`, но для данных, которых у экрана может не быть: подстановка без значения пропадает
 * вместе с пробелом перед ней («Договор подписан {date}» → «Договор подписан»)
 */
export function fillKnown(
  template: string,
  values: Record<string, string | number | null | undefined>,
): string {
  return template
    .replace(/\s*\{(\w+)\}/g, (whole: string, name: string) => {
      const value = values[name];
      if (value === undefined || value === null || value === '') return '';
      return whole.startsWith('{') ? String(value) : ` ${String(value)}`;
    })
    .trim();
}

/** Подстановка `{имя}` в строку словаря; неизвестное имя остаётся как есть (видно в тесте) */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) => {
    const value = values[name];
    return value === undefined ? whole : String(value);
  });
}

export interface ErrorView {
  /** Текст для человека */
  text: string;
  /** Подпись кнопки действия или null */
  action: string | null;
  /** Номер запроса для строки «Код для поддержки» */
  requestId: string | null;
  /** Код как есть (для data-атрибутов и тестов); не показываем человеку */
  code: string;
}

function lookup(code: string): ErrorText | null {
  return Object.prototype.hasOwnProperty.call(errorTexts, code)
    ? errorTexts[code as keyof typeof errorTexts]
    : null;
}

/**
 * Текст ошибки по `code` (а не по `detail`). Неизвестный код → общий текст и номер запроса.
 * `429` с `Retry-After` уточняет, через сколько секунд повторить.
 */
export function errorView(error: unknown): ErrorView {
  const appError: AppError = isAppError(error) ? error : toAppError(error);
  const known = lookup(appError.code);
  const entry: ErrorText = known ?? genericError;
  let text: string = entry.text;
  if (appError.code === 'RATE_LIMITED' && appError.retryAfterSeconds !== null) {
    text = fill(retryAfterText, { seconds: formatSeconds(appError.retryAfterSeconds) });
  }
  return {
    text,
    action: entry.action ?? null,
    requestId: appError.requestId,
    code: appError.code,
  };
}
