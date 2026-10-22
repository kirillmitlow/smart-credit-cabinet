import type { LoanDetail, LoanOut, LoanPaymentOut } from '@/api/generated/model';

/** График из пар [основной долг, проценты]; даты по месяцам с 21 ноября 2026 */
export function makeSchedule(parts: [number, number][]): LoanPaymentOut[] {
  return parts.map(([principalRub, interestRub], index) => ({
    seq: index + 1,
    dueDate: `${2026 + Math.floor((10 + index) / 12)}-${String(((10 + index) % 12) + 1).padStart(2, '0')}-21`,
    principalRub,
    interestRub,
    totalRub: principalRub + interestRub,
    status: 'SCHEDULED',
  }));
}

/** Кредит с равными платежами: 300 000 ₽ на 3 месяца, платёж 103 000 ₽ в первом месяце */
export function makeAnnuityLoan(over: Partial<LoanDetail> = {}): LoanDetail {
  const schedule = makeSchedule([
    [100_000, 3_000],
    [100_000, 2_000],
    [100_000, 1_000],
  ]);
  return {
    id: 'loan-1',
    applicationId: 'app-1',
    contractNumber: 'КД-2026-000001',
    productCode: 'EXPRESS',
    kind: 'LOAN',
    repaymentType: 'ANNUITY',
    amountRub: 300_000,
    limitRub: null,
    outstandingRub: 300_000,
    ratePercent: '21.50',
    termMonths: 3,
    paymentRub: schedule[0]?.totalRub ?? null,
    loanAccount: '45206810000000000001',
    settlementAccount: '40702810000000000001',
    openedOn: '2026-10-21',
    status: 'ACTIVE',
    nextPayment: schedule[0] ?? null,
    schedule,
    ...over,
  };
}

/** Кредит под контракт: проценты каждый месяц, весь долг в последнем платеже */
export function makeBulletLoan(over: Partial<LoanDetail> = {}): LoanDetail {
  const schedule = makeSchedule([
    [0, 5_000],
    [0, 5_000],
    [300_000, 5_000],
  ]);
  return makeAnnuityLoan({
    id: 'loan-2',
    applicationId: 'app-2',
    contractNumber: 'КД-2026-000002',
    productCode: 'CONTRACT',
    repaymentType: 'BULLET',
    paymentRub: 5_000,
    nextPayment: schedule[0] ?? null,
    schedule,
    ...over,
  });
}

/** Кредитная линия: лимит и ставка, без графика */
export function makeCreditLine(over: Partial<LoanDetail> = {}): LoanDetail {
  return makeAnnuityLoan({
    id: 'loan-3',
    applicationId: 'app-3',
    contractNumber: 'КД-2026-000003',
    productCode: 'CREDIT_LINE',
    kind: 'CREDIT_LINE',
    repaymentType: 'REVOLVING',
    amountRub: 0,
    limitRub: 1_000_000,
    outstandingRub: 0,
    paymentRub: null,
    nextPayment: null,
    schedule: [],
    ...over,
  });
}

/** Строка списка: то же без графика */
export function toListItem(loan: LoanDetail): LoanOut {
  const { schedule, ...item } = loan;
  void schedule;
  return item;
}
