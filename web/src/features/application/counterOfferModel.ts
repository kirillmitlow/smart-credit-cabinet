import type { VariantOut } from '@/api/generated/model';
import { formatMoney, formatTermMonths } from '@/lib/format';
import { productName } from '@/texts';

/** Одна строка «что изменилось против запроса»: значения уже отформатированы */
export interface VariantChange {
  field: 'product' | 'amount' | 'term';
  from: string;
  to: string;
}

function pair(value: unknown): { from: unknown; to: unknown } | null {
  if (typeof value !== 'object' || value === null) return null;
  const record = value as Record<string, unknown>;
  return 'from' in record && 'to' in record ? { from: record.from, to: record.to } : null;
}

/**
 * `whatChanged` приходит свободным словарём (OpenAPI не описывает ключи), поэтому читаем осторожно:
 * непонятное просто пропускаем. Ничего не считаем: разницу уже посчитал сервер.
 */
export function variantChanges(variant: VariantOut): VariantChange[] {
  const changes: VariantChange[] = [];
  const product = pair(variant.whatChanged.productCode);
  if (product && typeof product.from === 'string' && typeof product.to === 'string') {
    changes.push({
      field: 'product',
      from: productName(product.from) ?? product.from,
      to: productName(product.to) ?? product.to,
    });
  }
  const amount = pair(variant.whatChanged.amountRub);
  if (amount && typeof amount.from === 'number' && typeof amount.to === 'number') {
    changes.push({ field: 'amount', from: formatMoney(amount.from), to: formatMoney(amount.to) });
  }
  const term = pair(variant.whatChanged.termMonths);
  if (term && typeof term.from === 'number' && typeof term.to === 'number') {
    changes.push({
      field: 'term',
      from: formatTermMonths(term.from),
      to: formatTermMonths(term.to),
    });
  }
  return changes;
}

/** «Что нужно от вас»: фразы готовит сервер; нет ключа — ничего не нужно */
export function variantRequirements(variant: VariantOut): string[] {
  const value = variant.whatChanged.requirements;
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
    : [];
}

/** Нужен ли залог или поручительство, а сервер при этом ничего не написал в «что нужно от вас» */
export function needsSecurityFallback(variant: VariantOut): boolean {
  return (
    (variant.collateralRequired || variant.whatChanged.security === true) &&
    variantRequirements(variant).length === 0
  );
}

/** Платёж «только проценты»: основной долг в первом платеже графика равен нулю */
export function isInterestOnly(variant: VariantOut): boolean {
  const first = variant.schedulePreview[0];
  return first !== undefined && first.principalRub === 0;
}

/** Строки без повторов, порядок сохраняется */
export function uniqueLines(lines: readonly string[]): string[] {
  return [...new Set(lines.map((line) => line.trim()).filter((line) => line !== ''))];
}
