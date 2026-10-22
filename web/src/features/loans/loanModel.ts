import type { LoanOut, LoanPaymentOut } from '@/api/generated/model';
import { loansTexts } from '@/texts';

export type RepaymentType = keyof typeof loansTexts.repayment;

/** Линия и овердрафт: только лимит и ставка, графика и «остатка» нет (D-093) */
export function isLimitLoan(loan: Pick<LoanOut, 'kind' | 'repaymentType'>): boolean {
  return (
    loan.repaymentType === 'REVOLVING' || loan.kind === 'CREDIT_LINE' || loan.kind === 'OVERDRAFT'
  );
}

export function repaymentOf(loan: Pick<LoanOut, 'repaymentType'>): RepaymentType | null {
  return Object.prototype.hasOwnProperty.call(loansTexts.repayment, loan.repaymentType)
    ? (loan.repaymentType as RepaymentType)
    : null;
}

/** Статус кредита словами клиента; незнакомый статус не показываем «как есть» */
export function loanStatusLabel(status: string): string | null {
  return Object.prototype.hasOwnProperty.call(loansTexts.status, status)
    ? loansTexts.status[status as keyof typeof loansTexts.status]
    : null;
}

/** Сумма или лимит: у линии и овердрафта показываем лимит */
export function loanLimitOrAmount(loan: LoanOut): number {
  return isLimitLoan(loan) ? (loan.limitRub ?? loan.amountRub) : loan.amountRub;
}

export interface ScheduleLine extends LoanPaymentOut {
  /** Долг после этого платежа: выданная сумма минус сумма погашенного основного долга по графику */
  balanceRub: number;
}

export function withBalances(schedule: LoanPaymentOut[], amountRub: number): ScheduleLine[] {
  let balance = amountRub;
  return [...schedule]
    .sort((a, b) => a.seq - b.seq)
    .map((row) => {
      balance -= row.principalRub;
      return { ...row, balanceRub: balance };
    });
}

export interface ScheduleTotals {
  totalRub: number;
  principalRub: number;
  interestRub: number;
}

export function scheduleTotals(schedule: LoanPaymentOut[]): ScheduleTotals {
  return schedule.reduce<ScheduleTotals>(
    (sum, row) => ({
      totalRub: sum.totalRub + row.totalRub,
      principalRub: sum.principalRub + row.principalRub,
      interestRub: sum.interestRub + row.interestRub,
    }),
    { totalRub: 0, principalRub: 0, interestRub: 0 },
  );
}
