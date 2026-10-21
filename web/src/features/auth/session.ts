/**
 * Кто пользователь и что настроено на стенде. Клиентская сессия и публичная настройка идут через
 * сгенерированные функции orval (`GET /me`, `GET /public-config`). Входа банка в api ещё нет:
 * для банковской зоны спрашиваем `GET /me?zone=bank` руками; пока api читает только `sid_client`,
 * ответ «клиент» или `401` и даёт экран «Эта часть для сотрудников банка» либо вход (Q-146).
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { apiGet } from '@/api/client';
import { isAppError } from '@/api/errors';
import { getMe, getPublicConfig } from '@/api/generated/api';
import type { MeResponse, PublicConfig } from '@/api/generated/model';
import { publicConfigQueryKey, sessionQueryKey } from '@/api/session-keys';
import type { Zone } from '@/api/zone';

/** Ответ `GET /me` целиком: пользователь, роль и компании в форме схемы api */
export type Me = MeResponse;

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
        return await apiGet<Me>('/me?zone=bank', signal);
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
