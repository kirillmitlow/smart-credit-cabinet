import { describe, expect, it } from 'vitest';
import {
  NBSP,
  formatDate,
  formatDateLong,
  formatDateTime,
  formatInteger,
  formatMoney,
  formatPercent,
  formatSeconds,
  formatTermMonths,
  plural,
} from './format';

const nb = (text: string) => text.replaceAll(' ', NBSP);

describe('formatMoney', () => {
  it.each([
    [0, '0 ₽'],
    [5, '5 ₽'],
    [999, '999 ₽'],
    [1000, '1 000 ₽'],
    [1_234_567, '1 234 567 ₽'],
    [1_500_000, '1 500 000 ₽'],
    [15_000_000, '15 000 000 ₽'],
    [-46_000, '−46 000 ₽'],
    [1234.5, '1 235 ₽'],
    [123_456_789_012_345, '123 456 789 012 345 ₽'],
    [1e21, '1 000 000 000 000 000 000 000 ₽'],
  ])('%s → %s', (input, expected) => {
    expect(formatMoney(input)).toBe(nb(expected));
  });

  it('использует неразрывные пробелы', () => {
    expect(formatMoney(1_234_567)).toContain(NBSP);
    expect(formatMoney(1_234_567)).not.toContain(' ');
  });

  it('поддерживает bigint', () => {
    expect(formatMoney(12_345_678_901_234_567_890n)).toBe(nb('12 345 678 901 234 567 890 ₽'));
  });

  it.each([null, undefined, Number.NaN, Number.POSITIVE_INFINITY])('%s → тире', (input) => {
    expect(formatMoney(input)).toBe('—');
  });

  it('отрицательный ноль не превращается в «−0»', () => {
    expect(formatMoney(-0)).toBe(nb('0 ₽'));
    expect(formatMoney(-0.4)).toBe(nb('0 ₽'));
  });
});

describe('formatInteger', () => {
  it('группирует разряды', () => {
    expect(formatInteger(1234)).toBe(`1${NBSP}234`);
    expect(formatInteger(-1234)).toBe(`−1${NBSP}234`);
  });
});

describe('formatPercent', () => {
  it.each([
    [21.5, '21,5%'],
    [21, '21%'],
    [0, '0%'],
    [0.05, '0,05%'],
    [12.345, '12,35%'],
    [99.999, '100%'],
    [-3.5, '−3,5%'],
    [-0.001, '0%'],
    [1234.5, `1${NBSP}234,5%`],
  ])('%s → %s', (input, expected) => {
    expect(formatPercent(input)).toBe(expected);
  });

  it('учитывает число знаков', () => {
    expect(formatPercent(21.456, 1)).toBe('21,5%');
    expect(formatPercent(21.456, 0)).toBe('21%');
  });

  it.each([null, undefined, Number.NaN])('%s → тире', (input) => {
    expect(formatPercent(input)).toBe('—');
  });
});

describe('даты', () => {
  it('короткая: 21 окт 2026', () => {
    expect(formatDate('2026-10-21')).toBe(nb('21 окт 2026'));
    expect(formatDate('2026-05-01')).toBe(nb('1 мая 2026'));
  });

  it('длинная: 28 октября (с годом по просьбе)', () => {
    expect(formatDateLong('2026-10-28')).toBe(nb('28 октября'));
    expect(formatDateLong('2026-10-28', { withYear: true })).toBe(nb('28 октября 2026'));
  });

  it('дата без времени не сдвигается часовым поясом', () => {
    expect(formatDate('2026-01-01')).toBe(nb('1 янв 2026'));
    expect(formatDate('2026-12-31')).toBe(nb('31 дек 2026'));
  });

  it('момент в UTC показывается по Москве (UTC+3)', () => {
    expect(formatDateTime('2026-10-21T09:04:00Z')).toBe(`21${NBSP}октября, 12:04`);
    // 22:30 UTC — уже следующий день в Москве
    expect(formatDate('2026-10-20T22:30:00Z')).toBe(nb('21 окт 2026'));
  });

  it('принимает Date', () => {
    expect(formatDate(new Date('2026-10-21T09:04:00Z'))).toBe(nb('21 окт 2026'));
  });

  it.each([null, undefined, '', 'не дата'])('%s → тире', (input) => {
    expect(formatDate(input)).toBe('—');
    expect(formatDateLong(input)).toBe('—');
    expect(formatDateTime(input)).toBe('—');
  });
});

describe('срок и склонение', () => {
  it.each([
    [1, '1 месяц'],
    [2, '2 месяца'],
    [4, '4 месяца'],
    [5, '5 месяцев'],
    [11, '11 месяцев'],
    [12, '12 месяцев'],
    [21, '21 месяц'],
    [22, '22 месяца'],
    [24, '24 месяца'],
    [111, '111 месяцев'],
    [0, '0 месяцев'],
  ])('%s → %s', (months, expected) => {
    expect(formatTermMonths(months)).toBe(nb(expected));
  });

  it('plural работает с отрицательными и дробными', () => {
    expect(plural(-1, ['день', 'дня', 'дней'])).toBe('день');
    expect(plural(2.7, ['день', 'дня', 'дней'])).toBe('дня');
  });

  it('секунды', () => {
    expect(formatSeconds(1)).toBe(nb('1 секунду'));
    expect(formatSeconds(3)).toBe(nb('3 секунды'));
    expect(formatSeconds(30)).toBe(nb('30 секунд'));
  });

  it('пустой срок → тире', () => {
    expect(formatTermMonths(null)).toBe('—');
    expect(formatTermMonths(Number.NaN)).toBe('—');
  });
});
