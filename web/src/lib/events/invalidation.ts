import type { QueryClient, QueryKey } from '@tanstack/react-query';

/**
 * Области кэша, которые сбрасывают события потока (60-01, «Живые события»; 50-11).
 * Ключи сгенерированных хуков содержат адрес ручки (`/api/v1/applications/…`), поэтому область находим
 * по подстроке в любой строковой части ключа. Руками написанные запросы называем так же.
 */
export const queryAreas = {
  applications: '/applications',
  home: '/home',
  tasks: '/tasks',
  notifications: '/notifications',
} as const;

export type QueryArea = keyof typeof queryAreas;

export function keyMatchesArea(queryKey: QueryKey, area: QueryArea): boolean {
  const needle = queryAreas[area];
  return queryKey.some((part) => typeof part === 'string' && part.includes(needle));
}

/** Какие области сбрасывает каждое событие. `resync` и `auth_expired` разбираем отдельно */
export const areasByEvent = {
  status_changed: ['applications', 'home'],
  step_done: ['applications', 'home'],
  task_created: ['tasks', 'notifications', 'home'],
} as const satisfies Record<string, readonly QueryArea[]>;

export type AreaEventType = keyof typeof areasByEvent;

export function invalidateAreas(client: QueryClient, areas: readonly QueryArea[]): Promise<void> {
  return client.invalidateQueries({
    predicate: (query) => areas.some((area) => keyMatchesArea(query.queryKey, area)),
  });
}

/** `resync`: пропущено слишком много событий — перечитываем всё, что сейчас на экране */
export function invalidateEverything(client: QueryClient): Promise<void> {
  return client.invalidateQueries();
}
