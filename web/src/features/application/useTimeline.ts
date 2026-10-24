import { getGetApplicationTimelineQueryKey, useGetApplicationTimeline } from '@/api/generated/api';
import type { ApplicationOut } from '@/api/generated/model';
import { isInFlight } from './statuses';
import { APPLICATION_POLL_MS } from './useApplication';

export function useTimeline(application: ApplicationOut | undefined) {
  const id = application?.id ?? '';
  return useGetApplicationTimeline(id, {
    query: {
      // После ответа клиенту / нового решения не показываем галочки прежней версии.
      queryKey: [...getGetApplicationTimelineQueryKey(id), application?.version],
      enabled: !!application && application.status !== 'DRAFT',
      select: (response) => {
        if (response.status !== 200) throw new Error(`Unexpected status ${response.status}`);
        return response.data;
      },
      refetchInterval: application && isInFlight(application.status) ? APPLICATION_POLL_MS : false,
    },
  });
}
