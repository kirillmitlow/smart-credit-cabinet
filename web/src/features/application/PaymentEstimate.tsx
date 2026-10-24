import { useMemo } from 'react';
import { Button, Stack, Text } from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import { calculatePayment } from '@/api/generated/api';
import type { PaymentRequest } from '@/api/generated/model';
import { formatMoney } from '@/lib/format';
import { applicationForm } from '@/texts';
import { conditionsSchema } from './conditionsSchema';

const t = applicationForm.conditions;
const EQUAL_PAYMENT_PRODUCTS = new Set(['EXPRESS', 'WORKING_CAPITAL', 'INVESTMENT']);

/** Preview only: financial formulas/rates stay in the existing server calculator. */
export function PaymentEstimate({
  productCode,
  amountRub,
  termMonths,
  compact = false,
}: {
  productCode?: string | null;
  amountRub?: number | string | null;
  termMonths?: number | string | null;
  compact?: boolean;
}) {
  const request = useMemo<PaymentRequest | null>(() => {
    if (!productCode || !EQUAL_PAYMENT_PRODUCTS.has(productCode)) return null;
    const parsed = conditionsSchema.safeParse({ productCode, amountRub, termMonths });
    return parsed.success ? parsed.data : null;
  }, [productCode, amountRub, termMonths]);
  const [debounced] = useDebouncedValue(request, 250);
  const current = JSON.stringify(request) === JSON.stringify(debounced);
  const query = useQuery({
    queryKey: ['payment-preview', debounced],
    enabled: request !== null && current,
    staleTime: 60_000,
    retry: false,
    queryFn: async ({ signal }) => {
      if (!debounced) throw new Error('Payment request is incomplete');
      const response = await calculatePayment(debounced, { signal });
      if (response.status !== 200) throw new Error('Unexpected calculator response');
      return response.data;
    },
  });
  const data = request && current ? query.data : undefined;
  const error = request && current ? query.error : null;
  const pending = request && (!current || query.isPending);
  if (compact && !request) return null;
  return (
    <Stack gap={2} aria-live="polite" data-testid={compact ? 'payment-review' : 'payment'}>
      <Text size="sm" c="dimmed">
        {t.paymentLabel}
      </Text>
      <Text fw={compact ? 600 : 700} size={compact ? 'md' : 'xl'}>
        {data
          ? formatMoney(data.paymentRub)
          : pending
            ? t.paymentLoading
            : error
              ? t.paymentFailed
              : t.paymentLater}
      </Text>
      {data ? (
        <Text size="sm" c="dimmed">
          {t.paymentNote}
        </Text>
      ) : null}
      {error ? (
        <Button
          variant="subtle"
          size="compact-sm"
          onClick={() => void query.refetch()}
          w="fit-content"
        >
          {t.paymentRetry}
        </Button>
      ) : null}
    </Stack>
  );
}
