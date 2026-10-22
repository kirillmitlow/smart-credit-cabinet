import { applicationStatusLabels, type ApplicationStatus } from '@/texts';

/** Конечные статусы (20-02): дальше заявка не меняется, опрос можно остановить */
export const TERMINAL_STATUSES: ReadonlySet<string> = new Set([
  'DISBURSED',
  'REJECTED',
  'WITHDRAWN',
  'EXPIRED',
]);

export function isKnownStatus(status: string): status is ApplicationStatus {
  return Object.prototype.hasOwnProperty.call(applicationStatusLabels, status);
}

/** Название статуса для клиента (60-06); незнакомый статус не показываем «как есть» */
export function statusLabel(status: string): string | null {
  return isKnownStatus(status) ? applicationStatusLabels[status] : null;
}

/** Идёт ли заявка: нужна ли странице опрос сервера, пока нет живых событий */
export function isInFlight(status: string): boolean {
  return status !== 'DRAFT' && !TERMINAL_STATUSES.has(status);
}

/** Шесть шагов клиентского таймлайна и пауза «Нужна ваша помощь» (20-02, «Что видит клиент») */
export type ClientStepKey =
  'submitted' | 'checking' | 'needsHelp' | 'evaluating' | 'decision' | 'signing' | 'money';

/** Какому шагу таймлайна соответствует статус; у отозванных и истёкших шага нет */
export function clientStepOf(status: string): ClientStepKey | null {
  switch (status) {
    case 'SUBMITTED':
      return 'submitted';
    case 'CHECKING':
      return 'checking';
    case 'NEEDS_INFO':
      return 'needsHelp';
    case 'MANUAL_REVIEW':
      return 'evaluating';
    case 'APPROVED':
    case 'COUNTER_OFFER':
    case 'REJECTED':
      return 'decision';
    case 'OFFER_ACCEPTED':
    case 'SIGNED':
      return 'signing';
    case 'DISBURSING':
    case 'DISBURSED':
      return 'money';
    default:
      return null;
  }
}
