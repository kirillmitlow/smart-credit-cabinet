import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { Zone } from '@/api/zone';
import { areasByEvent, invalidateAreas, invalidateEverything } from './invalidation';

/**
 * connecting — первое подключение (индикатор молчит); connected — «обновляется автоматически»;
 * reconnecting — «восстанавливаем связь…»; polling — «обновляем раз в 5 секунд» (запасной режим).
 */
export type StreamStatus = 'connecting' | 'connected' | 'reconnecting' | 'polling';

export const STREAM_PATH = '/api/v1/events/stream';
/** Пауза перед ручным переподключением: совпадает с `retry: 3000` сервера (50-11) */
export const RECONNECT_DELAY_MS = 3_000;
/** Столько неудачных попыток подряд — и переходим на опрос */
export const MAX_FAILURES_BEFORE_POLLING = 3;
export const POLL_INTERVAL_MS = 5_000;

const READY_STATE_CLOSED = 2;

const NAMED_EVENTS = [
  'status_changed',
  'step_done',
  'task_created',
  'resync',
  'auth_expired',
] as const;

export interface UseEventStreamOptions {
  zone: Zone;
  /** Поток открываем только при активной сессии */
  enabled: boolean;
  /** Сервер сообщил, что сессия закончилась */
  onAuthExpired?: () => void;
}

export function streamUrl(zone: Zone, lastEventId: string | null): string {
  const params = new URLSearchParams({ zone });
  // Браузер сам передаёт Last-Event-ID при своём переподключении. Если поток пришлось открыть заново
  // (браузер закрыл его после ошибки), заголовок не поставить, поэтому дублируем номер параметром.
  if (lastEventId) params.set('lastEventId', lastEventId);
  return `${STREAM_PATH}?${params.toString()}`;
}

/**
 * Один поток событий на вкладку (50-11, 60-01). Ничего не рисует: сбрасывает кэш запросов,
 * экран перечитывается обычным запросом. Возвращает состояние связи для индикатора.
 */
export function useEventStream({
  zone,
  enabled,
  onAuthExpired,
}: UseEventStreamOptions): StreamStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>('connecting');
  const authExpiredRef = useRef(onAuthExpired);

  useEffect(() => {
    authExpiredRef.current = onAuthExpired;
  }, [onAuthExpired]);

  useEffect(() => {
    if (!enabled) return;

    let disposed = false;
    let source: EventSource | null = null;
    let failures = 0;
    let lastEventId: string | null = null;
    let lastNumericId = -1;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    let wasDegraded = false;

    const stopPolling = () => {
      if (pollTimer !== undefined) clearInterval(pollTimer);
      pollTimer = undefined;
    };

    const startPolling = () => {
      if (pollTimer !== undefined) return;
      void invalidateEverything(queryClient);
      pollTimer = setInterval(() => void invalidateEverything(queryClient), POLL_INTERVAL_MS);
    };

    const handleMessage = (type: (typeof NAMED_EVENTS)[number], event: MessageEvent) => {
      const id = event.lastEventId;
      if (id) {
        const numeric = Number(id);
        // Повтор события (то же или меньшее число) пропускаем: кэш уже сброшен
        if (Number.isFinite(numeric)) {
          if (numeric <= lastNumericId && type !== 'resync' && type !== 'auth_expired') return;
          lastNumericId = Math.max(lastNumericId, numeric);
        }
        lastEventId = id;
      }
      if (type === 'auth_expired') {
        authExpiredRef.current?.();
        return;
      }
      if (type === 'resync') {
        void invalidateEverything(queryClient);
        return;
      }
      void invalidateAreas(queryClient, areasByEvent[type]);
    };

    const connect = () => {
      if (disposed) return;
      const es = new EventSource(streamUrl(zone, lastEventId));
      source = es;

      es.addEventListener('open', () => {
        if (disposed || source !== es) return;
        failures = 0;
        stopPolling();
        setStatus('connected');
        if (wasDegraded) {
          // Пока связи не было, события могли пройти мимо: перечитываем то, что на экране
          wasDegraded = false;
          void invalidateEverything(queryClient);
        }
      });

      for (const type of NAMED_EVENTS) {
        es.addEventListener(type, (event) => handleMessage(type, event));
      }

      es.addEventListener('error', () => {
        if (disposed || source !== es) return;
        failures += 1;
        wasDegraded = true;
        if (failures >= MAX_FAILURES_BEFORE_POLLING) {
          setStatus('polling');
          startPolling();
        } else {
          setStatus('reconnecting');
        }
        // CLOSED: браузер сам не переподключится (например, ответ не 200) — открываем заново
        if (es.readyState === READY_STATE_CLOSED) {
          es.close();
          if (reconnectTimer !== undefined) clearTimeout(reconnectTimer);
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      });
    };

    connect();

    return () => {
      disposed = true;
      source?.close();
      source = null;
      setStatus('connecting');
      if (reconnectTimer !== undefined) clearTimeout(reconnectTimer);
      stopPolling();
    };
  }, [zone, enabled, queryClient]);

  return enabled ? status : 'connecting';
}
