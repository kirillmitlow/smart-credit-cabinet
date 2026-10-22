/**
 * Тексты экрана для тестов берём из словаря интерфейса (60-06), а не копируем в тест:
 * поменяли слово в `src/texts` — тест следует за ним (70-05).
 */
export { fill } from '../../src/texts';
export {
  login,
  home,
  wizard,
  wizardResult,
  applicationForm,
  applicationPage,
  consents,
  decision,
  loansTexts,
  shell,
  timelineSteps,
} from '../../src/texts';
export { contractTexts } from '../../src/texts/contract';
export { forbiddenClientWords } from '../../src/texts/forbidden';

/** Любой пробел в суммах: интерфейс пишет «46 677 ₽» с неразрывными пробелами */
const SPACE = '[\\s\\u00a0\\u202f]';

/** Рубли для `toContainText`: «46 677 ₽» с любыми пробелами внутри */
export function money(amount: number): RegExp {
  const digits = new Intl.NumberFormat('ru-RU').format(amount).replace(/[\s\u00a0\u202f]/g, SPACE);
  return new RegExp(`${digits}${SPACE}₽`);
}

export { companyProfile } from '../../src/texts/companyProfile';
