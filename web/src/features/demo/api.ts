import { appErrorFromResponse } from '@/api/errors';
import { demoGetChaos, demoListPersonas } from '@/api/generated/api';
import { useQuery } from '@tanstack/react-query';

export const personaKey = ['demo', 'personas'];
export const chaosKey = ['demo', 'chaos'];
export function usePersonas(enabled = true) {
  return useQuery({
    queryKey: personaKey,
    enabled,
    staleTime: 30_000,
    queryFn: async ({ signal }) => {
      const r = await demoListPersonas({ signal });
      if (r.status !== 200) throw appErrorFromResponse(r.status, r.data, r.headers, null);
      return r.data;
    },
  });
}
export function useChaos(enabled = true) {
  return useQuery({
    queryKey: chaosKey,
    enabled,
    refetchInterval: 5000,
    queryFn: async ({ signal }) => {
      const r = await demoGetChaos({ signal });
      if (r.status !== 200) throw appErrorFromResponse(r.status, r.data, r.headers, null);
      return r.data;
    },
  });
}
