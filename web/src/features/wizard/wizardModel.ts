import type { WizardAnswers, WizardResult } from '@/api/generated/model';

/**
 * Ход мастера (10-07): какие вопросы и в каком порядке. Здесь только ветвление по слотам;
 * таблица «ответ → продукт» и порог суммы для залога лежат на бэкенде (30-13), фронт их не копирует.
 */

export type StepId =
  'purpose' | 'frequency' | 'payback' | 'govContract' | 'amount' | 'payment' | 'collateral';

/**
 * Ответы клиента. `undefined` — вопрос ещё не задан, `'UNKNOWN'` / `null` — «Не знаю»
 * (бэкенд подбирает без этого ответа, 10-07 принцип 3)
 */
export type Answers = WizardAnswers;

export const UNKNOWN = 'UNKNOWN' as const;

/** Уточняющие вопросы после «на что деньги» (10-07, колонка «Когда задаём») */
const REFINEMENTS: Readonly<Record<string, readonly StepId[]>> = {
  GOODS: ['frequency', 'payback'],
  ORDER: ['frequency', 'payback', 'govContract'],
  GAP: ['frequency', 'payback'],
  GROWTH: ['payback'],
};

/** Варианты «комфортного платежа» есть только у продуктов с ежемесячным платежом */
export function paymentOptionsOf(preview: WizardResult | null) {
  return preview?.primary?.comfortableOptions ?? [];
}

/**
 * Список вопросов для текущих ответов. «Платёж» и «залог» появляются только после предварительного
 * расчёта на бэкенде (`preview`): он говорит, есть ли варианты платежа и выше ли сумма порога залога.
 */
export function stepsFor(answers: Answers, preview: WizardResult | null): StepId[] {
  const steps: StepId[] = ['purpose', ...(REFINEMENTS[answers.purpose ?? ''] ?? []), 'amount'];
  if (preview) {
    if (paymentOptionsOf(preview).length > 0) steps.push('payment');
    if (preview.askCollateral) steps.push('collateral');
  }
  return steps;
}

/** Сколько всего шагов показывать: пока расчёта нет, считаем, что платёж и залог ещё впереди */
export function totalSteps(answers: Answers, preview: WizardResult | null): number {
  const base = stepsFor(answers, preview).length;
  return preview ? base : base + 2;
}

/** Ответы, которые относятся к текущему пути: устаревшие (после смены цели) в запрос не попадают */
export function relevantAnswers(answers: Answers, steps: readonly StepId[]): Answers {
  const result: Answers = {};
  if (steps.includes('purpose') && answers.purpose !== undefined) result.purpose = answers.purpose;
  if (steps.includes('frequency') && answers.frequency !== undefined) {
    result.frequency = answers.frequency;
  }
  if (steps.includes('payback') && answers.paybackHorizon !== undefined) {
    result.paybackHorizon = answers.paybackHorizon;
  }
  if (steps.includes('govContract') && answers.govContract !== undefined) {
    result.govContract = answers.govContract;
  }
  if (steps.includes('amount') && answers.amountRub !== undefined) {
    result.amountRub = answers.amountRub;
  }
  if (steps.includes('payment') && answers.termMonths !== undefined) {
    result.termMonths = answers.termMonths;
  }
  if (steps.includes('collateral') && answers.collateral !== undefined) {
    result.collateral = answers.collateral;
  }
  return result;
}

/** Расчёт «на лету» после суммы: без срока и залога, чтобы бэкенд сам сказал, нужны ли эти вопросы */
export function previewAnswers(answers: Answers): Answers {
  return relevantAnswers(answers, stepsFor(answers, null));
}

/** Что мастер передаёт в результат и обратно («Изменить ответы») */
export interface WizardLocationState {
  answers: Answers;
  applicationId: string | null;
}

export function isWizardLocationState(value: unknown): value is WizardLocationState {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<WizardLocationState>;
  return typeof candidate.answers === 'object' && candidate.answers !== null;
}

/** Состояние результата: ответы, id черновика и сам ответ бэкенда */
export interface ResultLocationState extends WizardLocationState {
  result: WizardResult;
}

export function isResultLocationState(value: unknown): value is ResultLocationState {
  if (!isWizardLocationState(value)) return false;
  const candidate = value as Partial<ResultLocationState>;
  return typeof candidate.result === 'object' && candidate.result !== null;
}
