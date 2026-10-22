import type { QueryClient } from '@tanstack/react-query';
import {
  getGetApplicationQueryKey,
  getGetApplicationOfferQueryKey,
  getGetApplicationDecisionQueryKey,
  type getApplicationResponse,
} from '@/api/generated/api';

/** Статус — из ответа действия; полномочия перечитываем, старую кнопку отзыва сразу скрываем. */
export function updateApplicationStatus(client: QueryClient, id: string, status: string) {
  client.setQueryData<getApplicationResponse>(getGetApplicationQueryKey(id), (old) =>
    old?.status === 200 ? { ...old, data: { ...old.data, status, allowedActions: [] } } : old,
  );
  void client.invalidateQueries({ queryKey: getGetApplicationQueryKey(id) });
  void client.invalidateQueries({ queryKey: getGetApplicationOfferQueryKey(id) });
  void client.invalidateQueries({ queryKey: getGetApplicationDecisionQueryKey(id) });
  void client.invalidateQueries({ queryKey: ['/applications'] });
}
