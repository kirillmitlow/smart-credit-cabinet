import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Stack } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useAcceptOffer } from '@/api/generated/api';
import type { OfferOut } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { contractTexts as t } from '@/texts/contract';
import { updateApplicationStatus } from './cache';

export interface OfferActionsProps {
  offer: OfferOut;
  variantId?: string;
  /** Подпись кнопки; по умолчанию «Принять и перейти к подписанию» */
  label?: string;
  /** Другая карточка уже отправляет выбор: эту кнопку на время гасим */
  disabled?: boolean;
  /** Сообщает, идёт ли сейчас запрос принятия (чтобы соседние карточки не нажимались) */
  onPendingChange?: (pending: boolean) => void;
  /** Что описывает кнопка для скринридера (id заголовка карточки) */
  describedBy?: string;
}

/** Выбранные условия сервер переносит в договор; фронт их не пересчитывает. */
export function OfferActions({
  offer,
  variantId,
  label,
  disabled = false,
  onPendingChange,
  describedBy,
}: OfferActionsProps) {
  const client = useQueryClient();
  const action = useActionKey();
  const accept = useAcceptOffer<unknown>({ request: action.request() });
  const busy = useRef(false);
  const [accepted, setAccepted] = useState(false);
  const ready = offer.status === 'OPEN' && offer.variantsStatus === 'READY';
  const pending = accept.isPending;

  useEffect(() => {
    onPendingChange?.(pending);
  }, [pending, onPendingChange]);

  const submit = async () => {
    if (!ready || busy.current || accepted) return;
    busy.current = true;
    try {
      const response = await accept.mutateAsync({
        offerId: offer.id,
        data: variantId ? { variantId } : {},
      });
      if (response.status === 200) {
        setAccepted(true);
        action.reset();
        updateApplicationStatus(client, offer.applicationId, response.data.applicationStatus);
      }
    } catch {
      // При сетевом повторе сохраняем тот же ключ действия.
    } finally {
      busy.current = false;
    }
  };

  return (
    <Stack gap="sm">
      {accept.error ? <ProblemAlert error={accept.error} /> : null}
      {accepted ? (
        <Alert color="green">{t.accepted}</Alert>
      ) : (
        <div>
          <Button
            disabled={!ready || disabled}
            loading={pending}
            aria-describedby={describedBy}
            onClick={() => void submit()}
          >
            {label ?? t.accept}
          </Button>
        </div>
      )}
    </Stack>
  );
}
