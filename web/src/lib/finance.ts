/**
 * Ориентировочный платёж для экрана «Условия» (60-03, шаг 1). Это не решение банка: ставка берётся
 * базовая по продукту, итоговую считает ядро после проверки. Когда появится калькулятор в api
 * (`POST /calculator/payment`), экран перейдёт на него.
 */

/** Базовые ставки каталога (10-06), % годовых */
export const BASE_RATE_PERCENT: Readonly<Record<string, number>> = {
  EXPRESS: 24,
  WORKING_CAPITAL: 21,
  CONTRACT: 20,
  CREDIT_LINE: 20,
  OVERDRAFT: 25,
  INVESTMENT: 19,
};

/** Продукты, которые гасятся равными платежами: только для них показываем платёж */
export const ANNUITY_PRODUCTS: ReadonlySet<string> = new Set([
  'EXPRESS',
  'WORKING_CAPITAL',
  'INVESTMENT',
]);

/** Равный ежемесячный платёж (рубли, округление до целого) */
export function monthlyPayment(amountRub: number, termMonths: number, ratePercent: number): number {
  if (!(amountRub > 0) || !(termMonths > 0)) return 0;
  const monthlyRate = ratePercent / 100 / 12;
  if (monthlyRate === 0) return Math.round(amountRub / termMonths);
  const factor = Math.pow(1 + monthlyRate, termMonths);
  return Math.round((amountRub * monthlyRate * factor) / (factor - 1));
}

/** Ориентировочный платёж по продукту или `null`, если для продукта платёж считается иначе */
export function indicativePayment(
  productCode: string | null | undefined,
  amountRub: number | null | undefined,
  termMonths: number | null | undefined,
): number | null {
  if (!productCode || !ANNUITY_PRODUCTS.has(productCode)) return null;
  const rate = BASE_RATE_PERCENT[productCode];
  if (rate === undefined || !amountRub || !termMonths) return null;
  return monthlyPayment(amountRub, termMonths, rate);
}
