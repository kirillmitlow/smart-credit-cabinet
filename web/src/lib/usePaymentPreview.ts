import { useDebouncedValue } from '@mantine/hooks';
import { useQuery } from '@tanstack/react-query';
import { calculatePayment } from '@/api/generated/api';
import type { PaymentRequest } from '@/api/generated/model';

/** Общий серверный расчёт: пауза ввода, отмена старого запроса и отсутствие устаревших чисел. */
export function usePaymentPreview(request: PaymentRequest | null) {
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
  return {
    data: request && current ? query.data : undefined,
    error: request && current ? query.error : null,
    pending: Boolean(request && (!current || query.isPending)),
    refetch: query.refetch,
  };
}
