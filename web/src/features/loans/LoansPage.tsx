import { Button, Stack, Text, Title } from '@mantine/core';
import { useInfiniteQuery } from '@tanstack/react-query';
import { getListLoansQueryKey, listLoans } from '@/api/generated/api';
import { ProblemAlert } from '@/components/ProblemAlert';
import { useActiveCompany } from '@/features/auth/useActiveCompany';
import { usePageHeading } from '@/lib/usePageHeading';
import { fill, loansTexts as t } from '@/texts';
import { LoansList } from './LoansList';

const PAGE_LIMIT = 100;

/** «Мои кредиты»: страницы одной компании, без потери уже загруженных при ошибке следующей. */
export function LoansPage() {
  const headingRef = usePageHeading(t.title);
  const { choice } = useActiveCompany();
  const loans = useInfiniteQuery({
    queryKey: [...getListLoansQueryKey({ limit: PAGE_LIMIT }), 'pages', choice?.company.id],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam, signal }) => {
      const result = await listLoans(
        { limit: PAGE_LIMIT, ...(pageParam ? { cursor: pageParam } : {}) },
        { signal },
      );
      if (result.status !== 200) throw new Error('Unexpected loan page response');
      return result.data;
    },
    getNextPageParam: (page) => page.nextCursor ?? undefined,
  });
  const items = loans.data
    ? [
        ...new Map(
          loans.data.pages.flatMap((page) => page.items).map((loan) => [loan.id, loan]),
        ).values(),
      ]
    : undefined;
  const more = () => void loans.fetchNextPage({ cancelRefetch: false });
  const retry = () => {
    if (loans.isFetchNextPageError) more();
    else void loans.refetch();
  };
  return (
    <Stack gap="lg">
      <Title order={1} ref={headingRef} tabIndex={-1}>
        {t.title}
      </Title>
      <LoansList items={items} isPending={loans.isPending} error={loans.error} onRetry={retry} />
      {items && loans.error ? <ProblemAlert error={loans.error} onAction={retry} /> : null}
      {items && items.length > 0 ? (
        <Text size="sm" c="dimmed" role="status">
          {fill(t.shown, { count: items.length })}
        </Text>
      ) : null}
      {loans.hasNextPage ? (
        <Button
          variant="light"
          loading={loans.isFetchingNextPage}
          disabled={loans.isFetching}
          onClick={more}
          w="fit-content"
        >
          {t.loadMore}
        </Button>
      ) : null}
    </Stack>
  );
}
