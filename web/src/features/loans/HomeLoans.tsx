import { Button, Group } from '@mantine/core';
import { Link } from 'react-router';
import { useListLoans } from '@/api/generated/api';
import { loansTexts as t } from '@/texts';
import { LoansList } from './LoansList';

const HOME_LIMIT = 3;

/** Блок «Мои кредиты» на главной: последние кредиты и ссылка на полный список */
export function HomeLoans() {
  const loans = useListLoans({ limit: HOME_LIMIT });
  const page = loans.data?.status === 200 ? loans.data.data : undefined;
  return (
    <>
      <LoansList
        items={page?.items}
        isPending={loans.isPending}
        error={loans.error}
        onRetry={() => {
          void loans.refetch();
        }}
      />
      {page && page.items.length > 0 ? (
        <Group>
          <Button component={Link} to="/loans" variant="subtle" px={0}>
            {t.home.all}
          </Button>
        </Group>
      ) : null}
    </>
  );
}
