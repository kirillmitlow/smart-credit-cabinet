import type { Zone } from '@/api/zone';

export interface LocationLike {
  pathname: string;
  search?: string;
  hash?: string;
}

/** Адрес входа с запоминанием, куда вернуть после входа (60-01, «Защита маршрутов») */
export function loginUrl(zone: Zone, from?: LocationLike, reason?: 'expired'): string {
  const params = new URLSearchParams();
  if (zone === 'bank') params.set('zone', 'bank');
  if (reason) params.set('reason', reason);
  if (from && from.pathname !== '/login') {
    params.set('next', `${from.pathname}${from.search ?? ''}${from.hash ?? ''}`);
  }
  const query = params.toString();
  return query ? `/login?${query}` : '/login';
}

/** Возвращаем только внутренние адреса: `next` приходит из адресной строки, ему нельзя верить */
export function safeNext(next: string | null): string | null {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/login')) {
    return null;
  }
  return next;
}
