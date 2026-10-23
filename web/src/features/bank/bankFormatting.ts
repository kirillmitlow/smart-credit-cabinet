import { bankCard as t } from '@/texts/bank';

export function bankNumber(value: number | null | undefined): string {
  return value === null || value === undefined
    ? t.noData
    : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 3 }).format(value);
}

export function bankLabel(labels: Readonly<Record<string, string>>, code: string): string {
  return Object.prototype.hasOwnProperty.call(labels, code) ? (labels[code] ?? code) : code;
}
