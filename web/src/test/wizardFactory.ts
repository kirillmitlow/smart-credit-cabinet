import type {
  ComfortableOption,
  Recommended,
  RejectedCandidate,
  WizardResult,
} from '@/api/generated/model';

/** Фабрики ответов мастера подбора: значения как у Соколовой, тест меняет только важное */

export function makeComfortableOption(
  overrides: Partial<ComfortableOption> = {},
): ComfortableOption {
  return {
    termMonths: 12,
    paymentRub: 46_677,
    overpaymentRub: 60_124,
    recommended: false,
    ...overrides,
  };
}

export const defaultOptions: ComfortableOption[] = [
  makeComfortableOption({ termMonths: 12, paymentRub: 46_677, overpaymentRub: 60_124 }),
  makeComfortableOption({
    termMonths: 24,
    paymentRub: 25_500,
    overpaymentRub: 112_000,
    recommended: true,
  }),
  makeComfortableOption({ termMonths: 36, paymentRub: 18_300, overpaymentRub: 158_800 }),
];

export function makeRecommended(overrides: Partial<Recommended> = {}): Recommended {
  return {
    productCode: 'EXPRESS',
    title: 'Экспресс-кредит',
    why: 'Небольшая сумма на оборудование: быстро и без залога',
    paymentRub: 46_677,
    paymentKind: 'ANNUITY',
    ratePercentFrom: 24,
    approximate: true,
    decisionTime: 'AUTO',
    documents: [],
    needsCollateral: false,
    needsContract: false,
    requiresSecurity: false,
    comfortableOptions: defaultOptions,
    ...overrides,
  };
}

export function makeRejected(overrides: Partial<RejectedCandidate> = {}): RejectedCandidate {
  return {
    productCode: 'OVERDRAFT',
    title: 'Овердрафт',
    reasons: [
      {
        code: 'NOT_BANK_CUSTOMER',
        text: 'Овердрафт доступен клиентам банка с оборотами от 6 месяцев',
        action: 'Откройте счёт у нас',
        availableFrom: '2027-04-22',
      },
    ],
    ...overrides,
  };
}

export function makeWizardResult(overrides: Partial<WizardResult> = {}): WizardResult {
  return {
    outcome: 'RECOMMENDED',
    ruleId: 'EQUIPMENT_SMALL',
    startPath: false,
    primary: makeRecommended(),
    alternative: null,
    rejected: [],
    hint: null,
    askCollateral: false,
    applicationId: 'draft-1',
    ...overrides,
  };
}

/** Основной продукт без вариантов платежа (линия): платёж только по процентам */
export function makeLineRecommended(overrides: Partial<Recommended> = {}): Recommended {
  return makeRecommended({
    productCode: 'CREDIT_LINE',
    title: 'Кредитная линия',
    why: 'Закупки повторяются: линию можно брать и возвращать в пределах лимита',
    paymentKind: 'INTEREST_ONLY',
    paymentRub: 8_300,
    ratePercentFrom: 20,
    comfortableOptions: [],
    ...overrides,
  });
}
