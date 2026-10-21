import { useCallback, useMemo, useRef } from 'react';
import { newId } from '@/lib/id';

export const IDEMPOTENCY_HEADER = 'Idempotency-Key';

export interface ActionKey {
  /** Текущий ключ действия: создаётся при первом обращении и сохраняется до `reset` */
  getKey: () => string;
  /** Параметры запроса для сгенерированной мутации: `mutate(vars, …)` с `request: action.request()` */
  request: () => { headers: Record<string, string> };
  /** Сбросить ключ: вызываем после успеха (следующее нажатие — новое действие) */
  reset: () => void;
}

/**
 * Ключ идемпотентности создаётся на ДЕЙСТВИЕ пользователя, а не на запрос (60-01, 50-07):
 * нажали «Отправить» → ключ создан → двойной клик или повтор после обрыва уходят с тем же ключом →
 * после успеха ключ сбрасывается.
 */
export function useActionKey(): ActionKey {
  const keyRef = useRef<string | null>(null);

  const getKey = useCallback(() => {
    keyRef.current ??= newId();
    return keyRef.current;
  }, []);

  const reset = useCallback(() => {
    keyRef.current = null;
  }, []);

  const request = useCallback(() => ({ headers: { [IDEMPOTENCY_HEADER]: getKey() } }), [getKey]);

  return useMemo(() => ({ getKey, request, reset }), [getKey, request, reset]);
}
