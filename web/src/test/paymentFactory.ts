import type { PaymentOut, PaymentRequest } from '@/api/generated/model';

/** Fixed oracle from API test_catalog_calculator; UI tests override the returned number. */
export function makePayment(
  input: PaymentRequest,
  overrides: Partial<PaymentOut> = {},
): PaymentOut {
  return {
    productCode: input.productCode,
    amountRub: input.amountRub,
    termMonths: input.termMonths,
    paymentKind: 'ANNUITY',
    paymentRub: 47_280,
    lastPaymentRub: 47_278,
    totalPaymentRub: 567_358,
    overpaymentRub: 67_358,
    ratePercent: 24,
    ratePercentFrom: 21.5,
    effectiveRatePercent: 26.82,
    approximate: true,
    ...overrides,
  };
}
