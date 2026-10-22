/**
 * Слова, которых нет в клиентских текстах (60-06, словарь «не говорим / говорим»; 70-07).
 * Файл читает только проверка словаря (`texts.test.ts`); сам он в проверяемые тексты не входит.
 */
export const forbiddenClientWords: readonly { label: string; pattern: RegExp }[] = [
  { label: 'аннуитетный', pattern: /аннуитет/i },
  { label: 'обеспечение', pattern: /обеспечени/i },
  { label: 'кассовый разрыв', pattern: /кассов\S*\s+разрыв/i },
  { label: 'цель кредитования', pattern: /цел\S*\s+кредитования/i },
  { label: 'грейд', pattern: /грейд/i },
  { label: 'скоринг', pattern: /скоринг/i },
  { label: 'DSCR', pattern: /dscr/i },
  { label: 'стоп-фактор', pattern: /стоп-?\s?фактор/i },
];
