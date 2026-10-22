import type { QueryClient } from '@tanstack/react-query';
import {
  getGetApplicationQueryKey,
  useGetApplication,
  type getApplicationResponse,
} from '@/api/generated/api';
import type { ApplicationOut } from '@/api/generated/model';
import { isInFlight } from './statuses';

/** Пока нет живых событий (SSE), страница заявки сама спрашивает сервер раз в несколько секунд */
export const APPLICATION_POLL_MS = 3_000;

/** Успешный ответ (ошибки уже превращены в AppError общим обработчиком) */
export function unwrapApplication(response: getApplicationResponse): ApplicationOut {
  if (response.status !== 200) throw new Error(`Unexpected status ${response.status}`);
  return response.data;
}

/**
 * Заявка по номеру с опросом: пока статус не конечный, перечитываем раз в `APPLICATION_POLL_MS`.
 * Черновик не опрашиваем: его правит сам человек, а опрос затёр бы набираемое.
 */
export function useApplication(id: string) {
  return useGetApplication(id, {
    query: {
      select: unwrapApplication,
      refetchInterval: (query) => {
        const response = query.state.data;
        const status = response?.status === 200 ? response.data.status : null;
        return status !== null && isInFlight(status) ? APPLICATION_POLL_MS : false;
      },
    },
  });
}

/** Положить свежий ответ мутации (черновик, отправка, отзыв) в кэш, чтобы экран не ждал перечитывания */
export function putApplication(client: QueryClient, application: ApplicationOut): void {
  client.setQueryData<getApplicationResponse>(getGetApplicationQueryKey(application.id), {
    data: application,
    status: 200,
    headers: new Headers(),
  });
}
