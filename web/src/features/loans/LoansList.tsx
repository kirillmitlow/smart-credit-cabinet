import { Button, Skeleton, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import type { LoanOut } from '@/api/generated/model';
import { ProblemAlert } from '@/components/ProblemAlert';
import { useActiveCompany } from '@/features/auth/useActiveCompany';
import { emptyStates, loansTexts as t } from '@/texts';
import { LoanCard } from './LoanCard';

export interface LoansListProps {
  items: LoanOut[] | undefined;
  isPending: boolean;
  error: unknown;
  onRetry: () => void;
}

/** Три состояния списка кредитов (загрузка, ошибка, пусто) и сами карточки; общий для главной и «Мои кредиты» */
export function LoansList({ items, isPending, error, onRetry }: LoansListProps) {
  const { canApply } = useActiveCompany();
  if (isPending) {
    return (
      <Stack gap="sm" role="status" aria-label={t.loading}>
        <Skeleton height={96} radius="md" />
      </Stack>
    );
  }
  if (!items) return <ProblemAlert error={error} onAction={onRetry} />;
  if (items.length === 0) {
    return (
      <Stack gap="sm" align="flex-start" data-testid="loans-empty">
        <Text>{emptyStates.loans}</Text>
        {canApply ? (
          <Button component={Link} to="/wizard" variant="light">
            {t.emptyAction}
          </Button>
        ) : null}
      </Stack>
    );
  }
  return (
    <Stack component="ul" gap="sm" p={0} m={0} style={{ listStyle: 'none' }}>
      {items.map((loan) => (
        <li key={loan.id}>
          <LoanCard loan={loan} />
        </li>
      ))}
    </Stack>
  );
}
