/**
 * Кто пользователь и что настроено на стенде. Эндпоинтов `GET /me` и `GET /public-config` в схеме api
 * пока нет (50-07, раздел «Вход и сессия»), поэтому запросы написаны руками. Когда ручки появятся
 * в OpenAPI, заменяем на сгенерированные хуки: остальной код про это не знает.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet } from '@/api/client';
import { isAppError } from '@/api/errors';
import { publicConfigQueryKey, sessionQueryKey } from '@/api/session-keys';
import type { Zone } from '@/api/zone';

export type Role = 'CLIENT' | 'GUARANTOR' | 'UNDERWRITER' | 'ADMIN';

export interface CompanyRef {
  id: string;
  inn: string;
  name: string;
}

export interface Me {
  user: { id: string; name: string };
  role: Role;
  companies: CompanyRef[];
  activeCompanyId: string | null;
}

export interface PublicConfig {
  demoMode: boolean;
  name?: string;
  version?: string;
  nluAvailable?: boolean;
}

export const ME_PATH = '/api/v1/me';
export const PUBLIC_CONFIG_PATH = '/api/v1/public-config';

export function isBankRole(role: Role): boolean {
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
        return await apiGet<Me>(`${ME_PATH}?zone=${zone}`, signal);
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
        return await apiGet<PublicConfig>(PUBLIC_CONFIG_PATH, signal);
      } catch (error) {
        if (isNotSignedIn(error)) return { demoMode: false };
        throw error;
      }
    },
  });
}
