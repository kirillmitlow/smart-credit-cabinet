/**
 * Проверка ИНН на лету (T-408): длина и контрольные цифры. Те же веса, что в api
 * (`companies/service.py`), чтобы опечатку ловить до запроса, а не после.
 */
const INN10_W = [2, 4, 10, 3, 5, 9, 4, 6, 8] as const;
const INN12_W1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8] as const;
const INN12_W2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8] as const;

function checkDigit(digits: string, weights: readonly number[]): string {
  const sum = weights.reduce((total, weight, index) => total + Number(digits[index]) * weight, 0);
  return String((sum % 11) % 10);
}

export type InnProblem = 'length' | 'checksum';

/** Только цифры, не больше 12: всё лишнее (пробелы, буквы) отбрасываем при вводе */
export function normalizeInn(raw: string): string {
  return raw.replace(/\D/g, '').slice(0, 12);
}

/** `null` — ИНН годится; иначе что именно не так */
export function innProblem(inn: string): InnProblem | null {
  if (!/^\d+$/.test(inn) || (inn.length !== 10 && inn.length !== 12)) return 'length';
  if (inn.length === 10) {
    return inn[9] === checkDigit(inn.slice(0, 9), INN10_W) ? null : 'checksum';
  }
  const first = inn[10] === checkDigit(inn.slice(0, 10), INN12_W1);
  const second = inn[11] === checkDigit(inn.slice(0, 11), INN12_W2);
  return first && second ? null : 'checksum';
}
