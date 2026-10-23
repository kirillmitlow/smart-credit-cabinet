import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  Anchor,
  Badge,
  Button,
  Group,
  Select,
  Skeleton,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core';
import { useInfiniteQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { appErrorFromResponse } from '@/api/errors';
import { getBackofficeQueue, getGetBackofficeQueueQueryKey } from '@/api/generated/api';
import { Status } from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { formatDateTime, formatMoney, formatTermMonths } from '@/lib/format';
import { usePageHeading } from '@/lib/usePageHeading';
import { fill, productName, productNames } from '@/texts';
import { bankWorkspace as t } from '@/texts/bank';
import { BankRecommendationView } from './BankRecommendationView';

const statusOptions = Object.entries(t.statusOptions).map(([value, label]) => ({ value, label }));
const products = [
  { value: '', label: t.allProducts },
  ...Object.entries(productNames).map(([value, label]) => ({ value, label })),
];

export function BankQueuePage() {
  const heading = usePageHeading(t.queueTitle);
  const [status, setStatus] = useState<Status>(Status.MANUAL_REVIEW);
  const [productCode, setProductCode] = useState('');
  const filters = { status, productCode: productCode || undefined, limit: 20 };
  const query = useInfiniteQuery({
    queryKey: [...getGetBackofficeQueueQueryKey(filters), 'infinite'],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam, signal }) => {
      const response = await getBackofficeQueue({ ...filters, cursor: pageParam }, { signal });
      if (response.status !== 200)
        throw appErrorFromResponse(response.status, response.data, response.headers, null);
      return response.data;
    },
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
  const items = query.data?.pages.flatMap((page) => page.items);
  const previous = useRef<{ filter: string; pages: number; ids: Set<string> } | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const filterKey = `${status}:${productCode}`;

  useEffect(() => {
    if (!query.data) return;
    const ids = new Set(query.data.pages.flatMap((page) => page.items.map((item) => item.id)));
    const before = previous.current;
    const added =
      before?.filter === filterKey && before.pages === query.data.pages.length
        ? new Set([...ids].filter((id) => !before.ids.has(id)))
        : new Set<string>();
    previous.current = { filter: filterKey, pages: query.data.pages.length, ids };
    setFresh(added);
    if (added.size) {
      const timer = setTimeout(() => setFresh(new Set()), 2_000);
      return () => clearTimeout(timer);
    }
  }, [query.data, filterKey]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <div>
          <Title order={1} ref={heading} tabIndex={-1}>
            {t.queueTitle}
          </Title>
          <Text size="sm" c="dimmed">
            {t.queueIntro}
          </Text>
        </div>
        <Button variant="light" loading={query.isFetching} onClick={() => void query.refetch()}>
          {t.refresh}
        </Button>
      </Group>
      <Group align="end">
        <Select
          label={t.statusFilter}
          data={statusOptions}
          value={status}
          allowDeselect={false}
          onChange={(value) => {
            const found = Object.values(Status).find((candidate) => candidate === value);
            if (found) setStatus(found);
          }}
        />
        <Select
          label={t.productFilter}
          data={products}
          value={productCode}
          allowDeselect={false}
          onChange={(value) => setProductCode(value ?? '')}
        />
      </Group>
      {query.isError ? (
        <ProblemAlert error={query.error} onAction={() => void query.refetch()} />
      ) : null}
      {query.isPending ? (
        <Stack role="status" aria-label={t.loading}>
          <Skeleton height={100} />
          <Text>{t.loading}</Text>
        </Stack>
      ) : null}
      {items?.length === 0 && !query.isError ? (
        <Alert color="gray">
          {status === Status.MANUAL_REVIEW && !productCode ? t.empty : t.emptyFilter}
        </Alert>
      ) : null}
      {items && items.length > 0 ? (
        <Table.ScrollContainer minWidth={900}>
          <Table striped highlightOnHover verticalSpacing="sm" aria-label={t.queueTitle}>
            <Table.Thead>
              <Table.Tr>
                {Object.values(t.columns).map((label) => (
                  <Table.Th key={label} scope="col">
                    {label}
                  </Table.Th>
                ))}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((item) => (
                <Table.Tr
                  key={item.id}
                  data-testid={`bank-queue-${item.id}`}
                  data-fresh={fresh.has(item.id) || undefined}
                  bg={fresh.has(item.id) ? 'red.0' : undefined}
                >
                  <Table.Td>
                    <Stack gap={3}>
                      <Anchor
                        component={Link}
                        to={`/bank/applications/${item.id}?expectedVersion=${item.version}`}
                      >
                        {item.number}
                      </Anchor>
                      <Text size="xs">{formatDateTime(item.waitingSince)}</Text>
                      <Text size="sm" c={item.overdue ? 'red.8' : undefined}>
                        {fill(t.waiting, {
                          hours: Math.floor(item.waitingSeconds / 3600),
                          minutes: Math.floor(item.waitingSeconds / 60) % 60,
                        })}
                      </Text>
                      {item.overdue ? (
                        <Text size="xs" c="red.8">
                          {t.overdue}
                        </Text>
                      ) : null}
                      {item.badges.map((badge) => (
                        <Badge
                          key={badge}
                          variant="light"
                          color={badge === 'CLIENT_ANSWERED' ? 'blue' : 'red'}
                          c="dark.9"
                          style={{ height: 'auto', whiteSpace: 'normal' }}
                        >
                          {t.badges[badge]}
                        </Badge>
                      ))}
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <Stack gap={3}>
                      <Text size="sm" fw={600}>
                        {item.company.name}
                      </Text>
                      <Text size="xs">{fill(t.inn, { inn: item.company.inn })}</Text>
                      <Text size="xs" c="dimmed">
                        {item.company.isBankCustomer === null
                          ? t.unknownClient
                          : item.company.isBankCustomer
                            ? t.client
                            : t.notClient}
                      </Text>
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{productName(item.productCode) ?? t.unknownProduct}</Text>
                    <Text size="sm">{formatMoney(item.amountRub)}</Text>
                    <Text size="sm">{formatTermMonths(item.termMonths)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Stack gap="xs">
                      {item.manualReasons.map((reason) => (
                        <div key={reason.code}>
                          <Text size="sm">{reason.title}</Text>
                          <Text size="xs" c="dimmed">
                            {reason.code}
                          </Text>
                        </div>
                      ))}
                      {!item.manualReasons.length ? <Text size="sm">{t.noReasons}</Text> : null}
                    </Stack>
                  </Table.Td>
                  <Table.Td>
                    <BankRecommendationView value={item.recommendation} />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      ) : null}
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
  );
}
