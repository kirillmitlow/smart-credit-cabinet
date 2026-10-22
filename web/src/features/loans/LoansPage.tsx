import { Stack, Text, Title } from '@mantine/core';
import { useListLoans } from '@/api/generated/api';
import { usePageHeading } from '@/lib/usePageHeading';
import { fill, loansTexts as t } from '@/texts';
import { LoansList } from './LoansList';

const PAGE_LIMIT = 100;

/** «Мои кредиты» (60-03 №15): список кредитов компании */
export function LoansPage() {
  const headingRef = usePageHeading(t.title);
  const loans = useListLoans({ limit: PAGE_LIMIT });
  const page = loans.data?.status === 200 ? loans.data.data : undefined;
  return (
    <Stack gap="lg">
      <Title order={1} ref={headingRef} tabIndex={-1}>
        {t.title}
      </Title>
      <LoansList
        items={page?.items}
        isPending={loans.isPending}
        error={loans.error}
        onRetry={() => {
          void loans.refetch();
        }}
      />
      {page?.nextCursor ? (
        <Text size="sm" c="dimmed">
          {fill(t.moreShown, { count: page.items.length })}
        </Text>
      ) : null}
    </Stack>
  );
}
