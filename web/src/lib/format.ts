/**
 * Форматирование денег, процентов, дат и сроков одной точкой (T-405, 60-06).
 * Примеры: `1 500 000 ₽`, `21,5%`, `21 окт 2026`, `28 октября`, `12 месяцев`.
 * Пробелы в суммах неразрывные, чтобы сумма не переносилась по строкам.
 */

export const NBSP = ' ';
const MINUS = '−';
const DASH = '—';

/** Все даты показываем по московскому времени: демо привязано к одному часовому поясу, тесты не зависят от ПК */
export const APP_TIME_ZONE = 'Europe/Moscow';

/** Склонение числительных: plural(2, ['месяц', 'месяца', 'месяцев']) → 'месяца' */
export function plural(count: number, forms: readonly [string, string, string]): string {
  const n = Math.abs(Math.trunc(count));
  const lastTwo = n % 100;
  const last = n % 10;
  if (lastTwo >= 11 && lastTwo <= 14) return forms[2];
  if (last === 1) return forms[0];
  if (last >= 2 && last <= 4) return forms[1];
  return forms[2];
}

function groupDigits(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, NBSP);
}

/** Целое число с неразрывными пробелами: 1234567 → `1 234 567` */
export function formatInteger(value: number | bigint): string {
  if (typeof value === 'number' && !Number.isFinite(value)) return DASH;
  const integer = typeof value === 'bigint' ? value : BigInt(Math.round(value));
  const negative = integer < 0n;
  const digits = (negative ? -integer : integer).toString();
  return (negative ? MINUS : '') + groupDigits(digits);
}

/** Деньги: целые рубли, `1 234 567 ₽`. Пустое значение и не число → тире */
export function formatMoney(rub: number | bigint | null | undefined): string {
  if (rub === null || rub === undefined) return DASH;
  if (typeof rub === 'number' && !Number.isFinite(rub)) return DASH;
  return `${formatInteger(rub)}${NBSP}₽`;
}

/** Проценты числом (`ratePercent: 21.5`) → `21,5%`; до двух знаков, лишние нули не показываем */
export function formatPercent(percent: number | null | undefined, maxFractionDigits = 2): string {
  if (percent === null || percent === undefined || !Number.isFinite(percent)) return DASH;
  const factor = 10 ** maxFractionDigits;
  const rounded = Math.round(Math.abs(percent) * factor) / factor;
  const [whole = '0', fraction] = rounded.toFixed(maxFractionDigits).split('.');
  const trimmed = fraction?.replace(/0+$/, '') ?? '';
  const sign = percent < 0 && rounded !== 0 ? MINUS : '';
  return `${sign}${groupDigits(whole)}${trimmed ? `,${trimmed}` : ''}%`;
}

const MONTHS_GENITIVE = [
  'января',
  'февраля',
  'марта',
  'апреля',
  'мая',
  'июня',
  'июля',
  'августа',
  'сентября',
  'октября',
  'ноября',
  'декабря',
] as const;

const MONTHS_SHORT = [
  'янв',
  'фев',
  'мар',
  'апр',
  'мая',
  'июн',
  'июл',
  'авг',
  'сен',
  'окт',
  'ноя',
  'дек',
] as const;

interface CalendarParts {
  year: number;
  month: number; // 1..12
  day: number;
  hour: number;
  minute: number;
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

const zoneFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: APP_TIME_ZONE,
  year: 'numeric',
  month: 'numeric',
  day: 'numeric',
  hour: 'numeric',
  minute: 'numeric',
  hourCycle: 'h23',
});

/** Дата `2026-10-20` — календарный день без часового пояса; момент `...Z` переводим в московское время */
function toParts(input: string | Date): CalendarParts | null {
  if (typeof input === 'string') {
    const match = DATE_ONLY.exec(input);
    if (match) {
      return {
        year: Number(match[1]),
        month: Number(match[2]),
        day: Number(match[3]),
        hour: 0,
        minute: 0,
      };
    }
  }
  const date = typeof input === 'string' ? new Date(input) : input;
  if (Number.isNaN(date.getTime())) return null;
  const parts: Record<string, number> = {};
  for (const part of zoneFormatter.formatToParts(date)) {
    if (part.type !== 'literal') parts[part.type] = Number(part.value);
  }
  return {
    year: parts.year ?? 0,
    month: parts.month ?? 1,
    day: parts.day ?? 1,
    hour: parts.hour ?? 0,
    minute: parts.minute ?? 0,
  };
}

/** `21 окт 2026` */
export function formatDate(input: string | Date | null | undefined): string {
  if (input === null || input === undefined) return DASH;
  const p = toParts(input);
  if (!p) return DASH;
  return `${p.day}${NBSP}${MONTHS_SHORT[p.month - 1]}${NBSP}${p.year}`;
}

/** `28 октября` (год добавляем, только если просят) */
export function formatDateLong(
  input: string | Date | null | undefined,
  options: { withYear?: boolean } = {},
): string {
  if (input === null || input === undefined) return DASH;
  const p = toParts(input);
  if (!p) return DASH;
  const base = `${p.day}${NBSP}${MONTHS_GENITIVE[p.month - 1]}`;
  return options.withYear ? `${base}${NBSP}${p.year}` : base;
}

/** `21 октября, 12:04` (время по Москве) */
export function formatDateTime(input: string | Date | null | undefined): string {
  if (input === null || input === undefined) return DASH;
  const p = toParts(input);
  if (!p) return DASH;
  const time = `${String(p.hour).padStart(2, '0')}:${String(p.minute).padStart(2, '0')}`;
  return `${p.day}${NBSP}${MONTHS_GENITIVE[p.month - 1]}, ${time}`;
}

/** Срок в месяцах: `12 месяцев`, `1 месяц`, `24 месяца` */
export function formatTermMonths(months: number | null | undefined): string {
  if (months === null || months === undefined || !Number.isFinite(months)) return DASH;
  return `${months}${NBSP}${plural(months, ['месяц', 'месяца', 'месяцев'])}`;
}

/** `N секунд` для подсказок «повторите через…» */
export function formatSeconds(seconds: number): string {
  return `${seconds}${NBSP}${plural(seconds, ['секунду', 'секунды', 'секунд'])}`;
}
