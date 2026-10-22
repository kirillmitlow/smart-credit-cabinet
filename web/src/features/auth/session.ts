/**
 * Независимые сессии клиента и банка: разные cookie, маршруты API и ключи кэша (D-085).
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { isAppError } from '@/api/errors';
import { getBankMe, getMe, getPublicConfig } from '@/api/generated/api';
import type { BankMeResponse, MeResponse, PublicConfig } from '@/api/generated/model';
import { publicConfigQueryKey, sessionQueryKey } from '@/api/session-keys';
import type { Zone } from '@/api/zone';

/** Ответ `GET /me` целиком: пользователь, роль и компании в форме схемы api */
export type Me = MeResponse & { level?: BankMeResponse['level'] };

export function isBankRole(role: string): boolean {
  return role === 'UNDERWRITER' || role === 'ADMIN';
}

/** 401 и 404 от `/me` значат «не вошли» (ручки может ещё не быть); остальное — настоящая ошибка */
function isNotSignedIn(error: unknown): boolean {
  return isAppError(error) && (error.status === 401 || error.status === 404);
}

/** `null` — не вошли. Другие ошибки (сеть, 5xx) остаются ошибкой запроса */
export function useSession(zone: Zone, enabled = true): UseQueryResult<Me | null> {
  return useQuery<Me | null>({
    queryKey: sessionQueryKey(zone),
    enabled,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      try {
        if (zone === 'client') return (await getMe({ signal })).data;
        const bank = (await getBankMe({ signal })).data;
        return { ...bank, activeCompanyId: null, companies: [] };
      } catch (error) {
        if (isNotSignedIn(error)) return null;
        throw error;
      }
    },
  });
}

/** Публичная настройка стенда: нужна ещё до входа. Если ручки нет, демо считаем выключенным */
export function usePublicConfig(): UseQueryResult<PublicConfig> {
  return useQuery<PublicConfig>({
    queryKey: publicConfigQueryKey,
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }) => {
      try {
        return (await getPublicConfig({ signal })).data;
      } catch (error) {
        if (isNotSignedIn(error)) {
          return { demoMode: false, productName: '', version: '', nluAvailable: false };
        }
        throw error;
      }
    },
  });
}
