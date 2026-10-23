import type { ClientDecisionOut, VariantOut } from '@/api/generated/model';
import { makeDecision } from './decisionFactory';

function variant(
  extra: Partial<VariantOut> & Pick<VariantOut, 'id' | 'kind' | 'label'>,
): VariantOut {
  return {
    productCode: 'WORKING_CAPITAL',
    productTitle: 'Оборотный кредит',
    amountRub: 8_000_000,
    termMonths: 36,
    ratePercent: 19.5,
    paymentRub: 295_274,
    lastPaymentRub: 295_280,
    overpaymentRub: 2_629_929,
    collateralRequired: false,
    recommended: false,
    whatChanged: {},
    note: '',
    schedulePreview: [
      {
        number: 1,
        paymentRub: 295_274,
        principalRub: 150_000,
        interestRub: 145_274,
        balanceRub: 7_850_000,
      },
    ],
    ...extra,
  };
}

/** Три карточки СнабКонтракта из 30-17 (запрос: 8 млн на 12 мес.) */
export function snabkontraktVariants(): VariantOut[] {
  return [
    variant({
      id: 'variant-longer',
      kind: 'LONGER_TERM',
      label: 'Ваша сумма, дольше срок',
      recommended: true,
      note: 'Сумма как вы просили, срок дольше: платёж 295 274 ₽ в месяц укладывается в доход бизнеса.',
      whatChanged: { termMonths: { from: 12, to: 36 } },
    }),
    variant({
      id: 'variant-less',
      kind: 'LESS_AMOUNT',
      label: 'Ваш срок, меньше сумма',
      amountRub: 3_400_000,
      termMonths: 12,
      paymentRub: 314_144,
      lastPaymentRub: 314_150,
      overpaymentRub: 369_728,
      note: 'Срок как вы просили, а сумма меньше: платёж 314 144 ₽ в месяц укладывается в доход бизнеса.',
      whatChanged: { amountRub: { from: 8_000_000, to: 3_400_000 } },
    }),
    variant({
      id: 'variant-contract',
      kind: 'OTHER_PRODUCT',
      label: 'Другой продукт или с залогом',
      productCode: 'CONTRACT',
      productTitle: 'Кредит под контракт',
      termMonths: 4,
      paymentRub: 130_000,
      lastPaymentRub: 8_130_000,
      overpaymentRub: 520_000,
      note: 'Кредит под контракт: ежемесячно платите только проценты (130 000 ₽), а основной долг возвращаете из оплаты заказчика.',
      whatChanged: {
        productCode: { from: 'WORKING_CAPITAL', to: 'CONTRACT' },
        termMonths: { from: 12, to: 4 },
        requirements: ['Подтвердить контракт № 17: основной долг гасится из оплаты заказчика'],
      },
      schedulePreview: [
        {
          number: 1,
          paymentRub: 130_000,
          principalRub: 0,
          interestRub: 130_000,
          balanceRub: 8_000_000,
        },
      ],
    }),
  ];
}

export function makeCounterDecision(
  extra: Partial<ClientDecisionOut> = {},
  variants: VariantOut[] = snabkontraktVariants(),
): ClientDecisionOut {
  return {
    ...makeDecision(),
    applicationStatus: 'COUNTER_OFFER',
    outcome: 'COUNTER_OFFER',
    headline: 'Есть другие варианты',
    terms: null,
    rateBreakdown: [],
    whatHelped: [],
    whatAffected: ['Платёж по запрошенным условиям слишком велик для выручки'],
    reasons: [
      {
        code: 'DSCR_LOW',
        text: 'Платёж по запрошенным условиям слишком велик для выручки',
        action: 'Рассмотрите больший срок или меньшую сумму',
      },
    ],
    nextSteps: ['Рассмотрите больший срок или меньшую сумму'],
    offer: {
      id: 'offer-1',
      applicationId: 'app-1',
      kind: 'COUNTER_OFFER',
      status: 'OPEN',
      variantsStatus: 'READY',
      expiresAt: '2026-11-20T10:00:00Z',
      acceptedVariantId: null,
      contractId: null,
      variants,
    },
    ...extra,
  };
}
