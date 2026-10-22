import { z } from 'zod';
import type { ApplicationOut } from '@/api/generated/model';
import { applicationForm } from '@/texts';
import type { DraftFields } from './useDraftAutosave';

const v = applicationForm.validation;

export const productCodes = [
  'EXPRESS',
  'WORKING_CAPITAL',
  'CONTRACT',
  'CREDIT_LINE',
  'OVERDRAFT',
  'INVESTMENT',
] as const;

export const MAX_AMOUNT_RUB = 1_000_000_000;
export const MAX_TERM_MONTHS = 120;

/** Правила шага «Условия»: те же границы, что у ручки черновика (`PATCH …/draft`) */
const productCode = z.string({ error: v.productRequired }).min(1, v.productRequired);
const amountRub = z
  .number({ error: v.amountRequired })
  .int(v.amountInvalid)
  .positive(v.amountInvalid)
  .max(MAX_AMOUNT_RUB, v.amountTooBig);
const termMonths = z
  .number({ error: v.termRequired })
  .int(v.termInvalid)
  .min(1, v.termInvalid)
  .max(MAX_TERM_MONTHS, v.termInvalid);

export const conditionsSchema = z.object({ productCode, amountRub, termMonths });

/** Значения полей формы: пустое число — пустая строка (так отдаёт поле ввода числа) */
export interface ConditionsForm {
  productCode: string;
  amountRub: number | string;
  termMonths: number | string;
}

export function toForm(application: ApplicationOut): ConditionsForm {
  return {
    productCode: application.productCode ?? '',
    amountRub: application.amountRub ?? '',
    termMonths: application.termMonths ?? '',
  };
}

/** В черновик уходят только поля, прошедшие проверку: неполный ввод не мешает сохранять остальное */
export function validFields(values: Partial<ConditionsForm>): DraftFields {
  const fields: DraftFields = {};
  const product = productCode.safeParse(values.productCode);
  if (product.success) fields.productCode = product.data;
  const amount = amountRub.safeParse(values.amountRub);
  if (amount.success) fields.amountRub = amount.data;
  const term = termMonths.safeParse(values.termMonths);
  if (term.success) fields.termMonths = term.data;
  return fields;
}

/** Поля, которых не хватает для отправки (в порядке экрана) */
export function missingFields(application: ApplicationOut): ('product' | 'amount' | 'term')[] {
  const missing: ('product' | 'amount' | 'term')[] = [];
  if (!application.productCode) missing.push('product');
  if (!application.amountRub) missing.push('amount');
  if (!application.termMonths) missing.push('term');
  return missing;
}
