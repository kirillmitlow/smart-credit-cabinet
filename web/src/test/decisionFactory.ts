import type { ClientDecisionOut, VariantOut } from '@/api/generated/model';

export function makeDecision(extra: Partial<ClientDecisionOut> = {}): ClientDecisionOut {
  const terms: VariantOut = {
    id: 'variant-1',
    kind: 'AS_REQUESTED',
    label: 'Как вы просили',
    productCode: 'EXPRESS',
    productTitle: 'Экспресс-кредит',
    amountRub: 500_000,
    termMonths: 12,
    ratePercent: 21.5,
    paymentRub: 46_677,
    lastPaymentRub: 46_679,
    overpaymentRub: 60_126,
    collateralRequired: false,
    recommended: true,
    whatChanged: {},
    note: '',
    schedulePreview: [
      {
        number: 1,
        paymentRub: 46_677,
        principalRub: 37_719,
        interestRub: 8_958,
        balanceRub: 462_281,
      },
      { number: 12, paymentRub: 46_679, principalRub: 45_857, interestRub: 822, balanceRub: 0 },
    ],
  };
  return {
    applicationId: 'app-1',
    applicationStatus: 'APPROVED',
    decisionId: 'decision-1',
    outcome: 'APPROVED',
    headline: 'Одобрено на запрошенных условиях',
    decidedAt: '2026-10-21T10:00:00Z',
    terms,
    rateBreakdown: [
      { label: 'Базовая ставка', percent: 19.5 },
      { label: 'Поправка на срок', percent: 2 },
    ],
    reasons: [],
    nextSteps: [],
    whatHelped: ['чистая кредитная история', 'стабильная выручка'],
    whatAffected: [],
    offer: {
      id: 'offer-1',
      applicationId: 'app-1',
      kind: 'AS_REQUESTED',
      status: 'OPEN',
      variantsStatus: 'READY',
      expiresAt: '2026-11-20T10:00:00Z',
      acceptedVariantId: null,
      contractId: null,
      variants: [terms],
    },
    ...extra,
  };
}
