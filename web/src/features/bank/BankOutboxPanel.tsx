import { useRef, useState } from 'react';
import { Alert, Anchor, Button, Group, Paper, Skeleton, Stack, Text, Title } from '@mantine/core';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { appErrorFromResponse, isAppError } from '@/api/errors';
import {
  getListBackofficeOutboxQueryKey,
  listBackofficeOutbox,
  retryBackofficeOutbox,
} from '@/api/generated/api';
import { ProblemAlert } from '@/components/ProblemAlert';
import { formatDateTime } from '@/lib/format';
import { newId } from '@/lib/id';
import { fill } from '@/texts';
import { bankOutbox as t } from '@/texts/bank';
import { bankLabel } from './bankFormatting';

export function BankOutboxPanel({ applicationId }: { applicationId?: string }) {
  const cache = useQueryClient();
  const keys = useRef(new Map<number, string>());
  const [notice, setNotice] = useState(false);
  const params = { applicationId, limit: 20 };
  const query = useInfiniteQuery({
    queryKey: [...getListBackofficeOutboxQueryKey(params), 'infinite'],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) => {
      const response = await listBackofficeOutbox({ ...params, cursor: pageParam }, { signal });
      if (response.status !== 200)
        throw appErrorFromResponse(response.status, response.data, response.headers, null);
      return response.data;
    },
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
  const mutation = useMutation({
    mutationFn: ({ id, key }: { id: number; key: string }) =>
      retryBackofficeOutbox(id, undefined, { headers: { 'Idempotency-Key': key } }),
    onSuccess: (_result, variables) => {
      keys.current.delete(variables.id);
      setNotice(true);
      void cache.invalidateQueries({
        predicate: (q) =>
          q.queryKey.some((p) => typeof p === 'string' && p.includes('/backoffice/outbox')),
      });
    },
  });
  const retry = (id: number) => {
    const key = keys.current.get(id) ?? newId();
    keys.current.set(id, key);
    setNotice(false);
    mutation.mutate({ id, key });
  };
  const recover = () => {
    if (isAppError(mutation.error) && mutation.error.code === 'OUTBOX_NOT_FAILED') {
      mutation.reset();
      void query.refetch();
    } else if (mutation.variables) mutation.mutate(mutation.variables);
  };
  const items = query.data?.pages.flatMap((page) => page.items);
  return (
    <Paper withBorder p="md" data-testid="bank-outbox">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={2} size="h3">
            {t.title}
          </Title>
          <Button
            variant="subtle"
            size="compact-sm"
            loading={query.isFetching}
            onClick={() => void query.refetch()}
          >
            {t.refresh}
          </Button>
        </Group>
        {notice ? (
          <Alert color="blue" role="status">
            {t.queued}
          </Alert>
        ) : null}
        {mutation.isError ? <ProblemAlert error={mutation.error} onAction={recover} /> : null}
        {query.isPending ? (
          <Stack role="status" aria-label={t.loading}>
            <Skeleton height={40} />
          </Stack>
        ) : null}
        {query.isError ? (
          <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
        ) : null}
        {items?.length === 0 && !query.isError ? (
          <Text size="sm" c="dimmed">
            {t.empty}
          </Text>
        ) : null}
        {items?.map((item) => (
          <Paper withBorder p="sm" key={item.id}>
            <Group justify="space-between" align="start">
              <Stack gap={3}>
                <Text fw={600} size="sm">
                  {fill(t.number, { id: item.id })} · {bankLabel(t.systems, item.targetSystem)}
                </Text>
                <Text size="xs" c="dimmed">
                  {item.eventType} · {fill(t.attempts, { count: item.attempts })}
                </Text>
                <Text size="xs">
                  {t.created}: {formatDateTime(item.createdAt)}
                </Text>
                {item.applicationId && !applicationId ? (
                  <Anchor
                    component={Link}
                    size="sm"
                    to={`/bank/applications/${item.applicationId}`}
                  >
                    {t.openApplication}
                  </Anchor>
                ) : null}
                {item.lastError ? (
                  <details>
                    <summary>{t.reason}</summary>
                    <Text size="sm" style={{ overflowWrap: 'anywhere' }}>
                      {item.lastError}
                    </Text>
                  </details>
                ) : null}
                {item.blockedReason ? (
                  <Text size="sm">{item.blockedReason === 'EXPIRED' ? t.expired : t.missing}</Text>
                ) : null}
              </Stack>
              <Button
                size="compact-sm"
                variant="light"
                disabled={!item.canRetry || mutation.isPending}
                loading={mutation.isPending && mutation.variables?.id === item.id}
                onClick={() => retry(item.id)}
              >
                {t.retry}
              </Button>
            </Group>
          </Paper>
        ))}
        {query.hasNextPage ? (
          <Button
            variant="light"
            loading={query.isFetchingNextPage}
            onClick={() => void query.fetchNextPage()}
          >
            {t.more}
          </Button>
        ) : null}
      </Stack>
    </Paper>
  );
}
