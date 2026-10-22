import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { usePatchApplicationDraft } from '@/api/generated/api';
import type { ApplicationOut } from '@/api/generated/model';
import { isAppError } from '@/api/errors';
import { useOnline } from '@/lib/useOnline';
import { putApplication } from './useApplication';

/** Поля заявки, которые правит экран «Условия» (все необязательные: черновик можно сохранять неполным) */
export interface DraftFields {
  productCode?: string;
  amountRub?: number;
  termMonths?: number;
}

export type SaveState =
  | { kind: 'idle' }
  | { kind: 'saving' }
  | { kind: 'saved'; at: Date }
  | { kind: 'error'; error: unknown }
  /** Другая вкладка изменила заявку: сохранять поверх нельзя, нужно обновить (VERSION_CONFLICT) */
  | { kind: 'conflict' };

export const AUTOSAVE_DELAY_MS = 1_000;

function sameFields(application: ApplicationOut, fields: DraftFields): boolean {
  return (
    (fields.productCode === undefined || fields.productCode === application.productCode) &&
    (fields.amountRub === undefined || fields.amountRub === application.amountRub) &&
    (fields.termMonths === undefined || fields.termMonths === application.termMonths)
  );
}

export interface DraftAutosave {
  state: SaveState;
  /** Запомнить изменения и сохранить через паузу в ~1 с */
  schedule: (fields: DraftFields) => void;
  /** Сохранить сразу (при уходе с шага и перед отправкой); `false` — не вышло или конфликт */
  flush: () => Promise<boolean>;
  /** Сбросить состояние конфликта после «Обновить» */
  clearConflict: () => void;
}

/**
 * Автосохранение черновика `PATCH …/draft` (60-03 №7): пауза ~1 с после последнего изменения,
 * одновременно в пути не больше одного запроса, `version` берётся из последнего ответа.
 * `VERSION_CONFLICT` останавливает сохранение: данные другой вкладки затирать нельзя.
 */
export function useDraftAutosave(
  application: ApplicationOut,
  delayMs: number = AUTOSAVE_DELAY_MS,
): DraftAutosave {
  const queryClient = useQueryClient();
  const online = useOnline();
  const patch = usePatchApplicationDraft();
  const mutateAsync = patch.mutateAsync;
  const [state, setState] = useState<SaveState>({ kind: 'idle' });

  const applicationRef = useRef(application);
  const versionRef = useRef(application.version);
  const pendingRef = useRef<DraftFields | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const inFlightRef = useRef<Promise<boolean> | null>(null);
  const conflictRef = useRef(false);
  const onlineRef = useRef(online);

  useEffect(() => {
    applicationRef.current = application;
    // чужая версия (после «Обновить» или перечитывания) становится опорной, пока мы сами не сохраняем
    if (inFlightRef.current === null && !conflictRef.current) {
      versionRef.current = application.version;
    }
  }, [application]);

  const run = useCallback(async (): Promise<boolean> => {
    if (conflictRef.current) return false;
    if (inFlightRef.current) return inFlightRef.current;
    const attempt = async (): Promise<boolean> => {
      let ok = true;
      while (pendingRef.current && !conflictRef.current) {
        const fields = pendingRef.current;
        pendingRef.current = null;
        if (sameFields(applicationRef.current, fields)) continue;
        setState({ kind: 'saving' });
        try {
          const response = await mutateAsync({
            applicationId: applicationRef.current.id,
            data: { version: versionRef.current, ...fields, answers: {} },
          });
          if (response.status !== 200) throw new Error(`Unexpected status ${response.status}`);
          versionRef.current = response.data.version;
          applicationRef.current = response.data;
          putApplication(queryClient, response.data);
          setState({ kind: 'saved', at: new Date() });
        } catch (error) {
          // непринятые изменения возвращаем в очередь, если пользователь не успел набрать новее
          const newer = pendingRef.current as DraftFields | null; // могло появиться, пока шёл запрос
          pendingRef.current = { ...fields, ...newer };
          if (isAppError(error) && error.code === 'VERSION_CONFLICT') {
            conflictRef.current = true;
            pendingRef.current = null;
            setState({ kind: 'conflict' });
          } else {
            setState({ kind: 'error', error });
          }
          ok = false;
          break;
        }
      }
      return ok && !conflictRef.current;
    };
    const promise = attempt().finally(() => {
      inFlightRef.current = null;
    });
    inFlightRef.current = promise;
    return promise;
  }, [mutateAsync, queryClient]);

  const schedule = useCallback(
    (fields: DraftFields) => {
      if (conflictRef.current) return;
      pendingRef.current = fields; // полный набор допустимых значений формы на сейчас
      if (timerRef.current !== undefined) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        timerRef.current = undefined;
        void run();
      }, delayMs);
    },
    [delayMs, run],
  );

  const flush = useCallback(async (): Promise<boolean> => {
    if (timerRef.current !== undefined) {
      clearTimeout(timerRef.current);
      timerRef.current = undefined;
    }
    if (inFlightRef.current) await inFlightRef.current;
    if (conflictRef.current) return false;
    if (!pendingRef.current) return true;
    return run();
  }, [run]);

  const clearConflict = useCallback(() => {
    conflictRef.current = false;
    pendingRef.current = null;
    versionRef.current = applicationRef.current.version;
    setState({ kind: 'idle' });
  }, []);

  // Связь вернулась: досылаем то, что не ушло
  useEffect(() => {
    const wasOffline = !onlineRef.current;
    onlineRef.current = online;
    if (online && wasOffline && pendingRef.current) void run();
  }, [online, run]);

  // Уходя со страницы, не теряем набранное: таймер снимаем и пробуем сохранить
  useEffect(() => {
    return () => {
      if (timerRef.current !== undefined) {
        clearTimeout(timerRef.current);
        timerRef.current = undefined;
        void run();
      }
    };
  }, [run]);

  return useMemo(
    () => ({ state, schedule, flush, clearConflict }),
    [state, schedule, flush, clearConflict],
  );
}
