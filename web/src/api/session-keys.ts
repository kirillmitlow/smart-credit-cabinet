import type { Zone } from './zone';

/** Ключ кэша «кто пользователь» (`GET /me`) отдельно для каждой зоны: сессии клиента и банка независимы (D-085) */
export function sessionQueryKey(zone: Zone) {
  return ['session', zone] as const;
}

export const publicConfigQueryKey = ['public-config'] as const;
