import { useListApplicationConsents } from '@/api/generated/api';

/** Состав и полномочия определяет сервер; опрос подхватывает подпись другого участника. */
export function useConsents(applicationId: string) {
  return useListApplicationConsents(applicationId, {
    query: {
      select: (response) => {
        if (response.status !== 200) throw new Error(`Unexpected status ${response.status}`);
        return response.data;
      },
      refetchInterval: (query) =>
        query.state.data?.status === 200 && query.state.data.data.allSigned ? false : 5_000,
    },
  });
}
