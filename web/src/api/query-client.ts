import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query';
import { isAppError } from './errors';
import { sessionQueryKey } from './session-keys';
import { currentZone } from './zone';

/** Повторяем только сбои сети и 5xx, и то недолго: 4xx — ответ сервера, повтор ничего не изменит */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  if (!isAppError(error)) return false;
  return error.status === 0 || error.status >= 500;
}

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (error) => handleGlobalError(client, error) }),
    mutationCache: new MutationCache({ onError: (error) => handleGlobalError(client, error) }),
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false, staleTime: 5_000 },
      mutations: { retry: false },
    },
  });
  return client;
}

/**
 * 401 в любом запросе = сессия закончилась: помечаем «не вошли» в текущей зоне,
 * защита маршрутов сама перенаправит на /login (60-01).
 */
function handleGlobalError(client: QueryClient, error: unknown): void {
  if (isAppError(error) && error.status === 401) {
    client.setQueryData(sessionQueryKey(currentZone()), null);
  }
}
