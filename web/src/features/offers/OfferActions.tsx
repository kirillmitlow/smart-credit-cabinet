import { useRef, useState } from 'react';
import { Alert, Button, Stack } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useAcceptOffer } from '@/api/generated/api';
import type { OfferOut } from '@/api/generated/model';
import { useActionKey } from '@/api/idempotency';
import { ProblemAlert } from '@/components/ProblemAlert';
import { contractTexts as t } from '@/texts/contract';
import { updateApplicationStatus } from './cache';

/** Выбранные условия сервер переносит в договор; фронт их не пересчитывает. */
export function OfferActions({ offer, variantId }: { offer: OfferOut; variantId?: string }) {
  const client = useQueryClient();
  const action = useActionKey();
  const accept = useAcceptOffer<unknown>({ request: action.request() });
  const busy = useRef(false);
  const [accepted, setAccepted] = useState(false);
  const ready = offer.status === 'OPEN' && offer.variantsStatus === 'READY';

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
          <Button disabled={!ready} loading={accept.isPending} onClick={() => void submit()}>
            {t.accept}
          </Button>
        </div>
      )}
    </Stack>
  );
}
